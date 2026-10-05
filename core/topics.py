from collections import defaultdict

STOPWORDS = set(
    "的 了 是 我 你 他 她 我们 你们 他们 这个 那个 一个 自己 什么 怎么 就是 还是 所以 但是 因为 然后 感觉 现在 知道 时候 不是 没有 还有 真的 这样 一样 只有 这种 这些 那些 已经 如果 这里 那就 有 没 不 都 就 在 也 又 要 很 会 能 给 把 到 从 这 那 着 吗 吧 呢 啊 哦 啦 呀 嗯 及 与 或 而 对 为".split()
)


def chinese_topic_tokens(text):
    import jieba

    return [
        word
        for token in jieba.lcut(text)
        if (word := token.strip())
        and any(c.isalnum() for c in word)
        and not word.isdigit()
        and word not in STOPWORDS
    ]


def discover_topics(rows, config):
    groups = defaultdict(list)
    for r in rows:
        if r["status"] == "SUCCESS" and r["analysis"]["methods"]:
            groups[r["cleaned_comment"]].append(r["comment_key"])
    base = {
        "model": config.get("model", "BAAI/bge-small-zh-v1.5"),
        "unique_documents": len(groups),
        "topics": [],
        "status": "INSUFFICIENT_DATA",
        "topic_ids_scope": "CURRENT_RUN",
    }
    if not config.get("enabled", True):
        return base | {"status": "DISABLED"}
    if len(groups) < config.get("min_documents", 50):
        return base
    try:
        import jieba
        from bertopic import BERTopic
        from sentence_transformers import SentenceTransformer
        from sklearn.feature_extraction.text import CountVectorizer
        from umap import UMAP
        from hdbscan import HDBSCAN

        texts = sorted(groups)
        encoder = SentenceTransformer(base["model"])
        embeddings = encoder.encode(
            texts, normalize_embeddings=True, show_progress_bar=False
        )
        model = BERTopic(
            embedding_model=encoder,
            umap_model=UMAP(
                n_neighbors=15,
                n_components=5,
                metric="cosine",
                random_state=config.get("seed", 42),
            ),
            hdbscan_model=HDBSCAN(
                min_cluster_size=config.get("min_cluster_size", 10),
                min_samples=config.get("min_samples", 5),
                prediction_data=True,
            ),
            vectorizer_model=CountVectorizer(
                tokenizer=chinese_topic_tokens, token_pattern=None
            ),
            verbose=False,
        )
        labels, _ = model.fit_transform(texts, embeddings)
        topics = defaultdict(list)
        for text, label in zip(texts, labels):
            topics[int(label)].append(text)
        for label, docs in sorted(topics.items()):
            words = [w for w, score in (model.get_topic(label) or [])[:8]]
            keys = [k for d in docs for k in groups[d]]
            base["topics"].append(
                {
                    "topic_id": label,
                    "name": "离群主题" if label == -1 else " / ".join(words[:4]),
                    "keywords": words,
                    "unique_texts": len(docs),
                    "comment_count": len(keys),
                    "comment_keys": keys,
                    "representatives": docs[:5],
                    "acceptance": "CANDIDATE_PENDING_HUMAN_REVIEW",
                }
            )
        return base | {"status": "SUCCESS"}
    except Exception as e:
        return base | {"status": "FAILED", "reason": type(e).__name__ + ": " + str(e)}
