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
        '<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>投资评论分析</title><style>body{max-width:1100px;margin:36px auto;font:16px/1.6 sans-serif}pre{white-space:pre-wrap}table{border-collapse:collapse}td,th{border:1px solid #ddd;padding:8px}article{border-top:1px solid #ddd;padding:15px}a{color:#1261a0}</style><h1>投资评论分析报告</h1><p>实验状态；人工准确性验收尚未完成。方向统计仅包含 SUCCESS，待复核与失败记录单列。</p>'
    ]
    for title, data in [
        ("运行与输入", manifest),
        ("质量与旧新差异", quality),
        ("方法分布", strategies),
        ("主题发现", topics),
    ]:
        parts.extend(
            [
                "<h2>"
                + title
                + "</h2><pre>"
                + escape(json.dumps(data, ensure_ascii=False, indent=2))
                + "</pre>"
            ]
        )
    parts.append(
        "<h2>标的榜</h2><table><tr><th>标的</th><th>提及</th><th>推荐</th><th>反对</th><th>方向样本</th><th>证据</th></tr>"
    )
    for a in ranks:
        links = " ".join(
            '<a href="#' + escape(k) + '">原文</a>'
            for k in a["representative_comments"]
        )
        parts.append(
            "<tr><td>"
            + escape(a["entity"]["name"])
            + "</td>"
            + "".join(
                "<td>" + escape(a[k]) + "</td>"
                for k in [
                    "mentions",
                    "recommend_count",
                    "oppose_count",
                    "directional_count",
                ]
            )
            + "<td>"
            + links
            + "</td></tr>"
        )
    parts.append("</table><h2>逐条原文及结构化分析</h2>")
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
