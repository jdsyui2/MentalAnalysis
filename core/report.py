import csv
import html
import json
from pathlib import Path
from urllib.parse import urlparse


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
        '<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>投资评论分析</title><style>body{max-width:1100px;margin:36px auto;font:16px/1.6 sans-serif}pre{white-space:pre-wrap}table{border-collapse:collapse}td,th{border:1px solid #ddd;padding:8px}article{border-top:1px solid #ddd;padding:15px}a{color:#1261a0}</style><h1>投资评论分析报告</h1><p>实验状态；人工准确性验收尚未完成。按字段校验统计，PARTIAL中的合法字段独立纳入；待复核与失败字段单列。</p>'
    ]
    parts.append(
        "<h2>投资选择</h2><table><tr><th>标的／类别</th><th>提及</th><th>明确推荐</th><th>上下文推荐</th><th>本人持仓</th><th>回避</th><th>卖出</th><th>方向样本</th><th>视频覆盖</th><th>证据</th></tr>"
    )
    for asset in ranks:
        links = " ".join(
            '<a href="#' + escape(k) + '">原文</a>'
            for k in asset["representative_comments"]
        )
        cells = (
            [asset["entity"]["name"] + " / " + asset["entity"]["category"]]
            + [
                asset[k]
                for k in [
                    "mentions",
                    "explicit_recommendation_count",
                    "context_recommendation_count",
                    "self_position_count",
                    "avoid_count",
                    "sell_count",
                    "directional_count",
                ]
            ]
            + [str(asset["video_count"]) + "/" + str(asset["video_total"])]
        )
        parts.append(
            "<tr>"
            + "".join("<td>" + escape(v) + "</td>" for v in cells)
            + "<td>"
            + links
            + "</td></tr>"
        )
    parts.append(
        "</table><h2>投资方法与态度</h2><p>多标签讨论；自用、提及和支持分别统计。净支持率分母为支持＋反对。</p><table><tr><th>方法</th><th>讨论</th><th>支持</th><th>反对</th><th>自用</th><th>询问</th><th>提及</th><th>未知</th><th>净支持率</th><th>方向样本</th></tr>"
    )
    for m in strategies.get("ranking", []):
        cells = (
            [m["method_name"], m["count"]]
            + [
                m["attitudes"].get(k, 0)
                for k in [
                    "SUPPORT",
                    "OPPOSE",
                    "SELF_PRACTICE",
                    "QUESTION",
                    "MENTION",
                    "UNKNOWN",
                ]
            ]
            + [
                f"{m['net_support_rate']:.1%}"
                if m["net_support_rate"] is not None
                else "—",
                "样本不足" if m["directional_count"] < 10 else m["directional_count"],
            ]
        )
        parts.append(
            "<tr>" + "".join("<td>" + escape(v) + "</td>" for v in cells) + "</tr>"
        )
    parts.append(
        "</table><h2>理由与分歧</h2><p>以下均为评论者陈述，未经外部核验；不足10个方向样本不作稳定共识判断。</p>"
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
