import csv
import html
import json
from pathlib import Path
from urllib.parse import urlparse
from .presentation import render_boards, LIMITATIONS, methods_with_evidence


def write_json(path, data):
    p = Path(path)
    temp = p.with_suffix(p.suffix + ".tmp")
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(p)


def csv_value(v):
    if isinstance(v, (int, float)):
        return str(v)
    s = (
        json.dumps(v, ensure_ascii=False)
        if isinstance(v, (dict, list))
        else ""
        if v is None
        else str(v)
    )
    return (
        "'" + s
        if s.lstrip().startswith(("=", "+", "-", "@"))
        or s.startswith(("\t", "\r", "\n"))
        else s
    )


def write_csv(path, rows):
    fields = list(dict.fromkeys(k for row in rows for k in row))
    with Path(path).open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows({k: csv_value(v) for k, v in r.items()} for r in rows)


def make_report(directory, rows, ranks, strategies, topics, quality, manifest):
    escape = lambda x: html.escape(str(x))
    parts = [
        '<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>投资评论分析</title><style>body{max-width:1100px;margin:36px auto;font:16px/1.6 sans-serif}pre{white-space:pre-wrap}table{border-collapse:collapse}td,th{border:1px solid #ddd;padding:8px}article{border-top:1px solid #ddd;padding:15px}a{color:#1261a0}</style><h1>投资评论分析报告</h1><p>RESEARCH_ASSIST · RESEARCH_ONLY · PENDING_HUMAN_ANNOTATION；工程就绪，研究辅助可用；模型准确率未验证，投资信号与ASDC因子未就绪。按字段校验统计，PARTIAL中的合法字段独立纳入；待复核与失败字段单列。</p>'
    ]
    parts.append("<p>" + escape(LIMITATIONS) + "</p>")
    parts.append(render_boards(ranks, methods_with_evidence(strategies, rows)))
    parts.append(
        "<h2>理由与分歧</h2><p>以下均为评论者陈述，未经外部核验；不足10个方向样本不作稳定共识判断。</p>"
    )
    for asset in ranks:
        if not asset["rationales"]:
            continue
        parts.append("<h3>" + escape(asset["entity"]["name"]) + "</h3><ul>")
        for rr in asset["rationales"][:6]:
            refs = " ".join(
                '<a href="#' + escape(ev["comment_key"]) + '">证据</a>'
                for ev in rr["evidence"][:3]
            )
            parts.append(
                "<li>"
                + escape(
                    rr["reason_code"] + " / " + rr["stance"] + "：" + rr["summary"]
                )
                + "（"
                + escape(rr["mentions"])
                + "条） "
                + refs
                + "</li>"
            )
        parts.append("</ul>")
    parts.append(
        "<h2>候选主题</h2><p>四个主题空间；自动主题尚待人工相关率验收。</p><ul>"
    )
    for t in topics.get("topics", []):
        parts.append(
            "<li>"
            + escape(t["space"] + " / " + t["name"])
            + "："
            + escape(t["comment_count"])
            + "条</li>"
        )
    parts.append("</ul><h2>质量与复现信息</h2>")
    for title, data in [
        ("运行与输入", manifest),
        ("质量与旧新差异", quality),
        ("完整方法统计", strategies),
        ("完整主题结果", topics),
    ]:
        parts.append(
            "<details><summary>"
            + escape(title)
            + "</summary><pre>"
            + escape(json.dumps(data, ensure_ascii=False, indent=2))
            + "</pre></details>"
        )
    parts.append("<h2>逐条原文及结构化分析</h2>")

    for r in rows:
        url = r.get("video_url")
        link = ""
        if url and urlparse(url).scheme in ("https", "http"):
            link = '<a href="' + escape(url) + '">来源视频</a>'
        parts.extend(
            [
                '<article id="'
                + escape(r["comment_key"])
                + '"><b>'
                + escape(r["comment_key"])
                + " · "
                + escape(r["status"])
                + "</b> "
                + link,
                "<p>"
                + escape(r["raw_comment"])
                + "</p><pre>"
                + escape(
                    json.dumps(
                        {
                            "sources": r["sources"],
                            "analysis": r.get("analysis"),
                            "reason": r.get("reason"),
                        },
                        ensure_ascii=False,
                        indent=2,
                    )
                )
                + "</pre></article>",
            ]
        )
    parts.append("</html>")
    (Path(directory) / "report.html").write_text("\n".join(parts), encoding="utf-8")
