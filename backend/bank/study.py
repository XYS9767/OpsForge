"""Export paired oral answers as a portable Markdown study document."""
from datetime import datetime


def markdown(questions, total=None, start=0, header=True):
    output = [
        "# OpsForge · 口述题背题册", "",
        f"生成日期：{datetime.now():%Y-%m-%d}　题数：{len(questions) if total is None else total}", "",
        "先遮住答案，自己说一遍，再展开核对。答案是表达示例，不要把其中的处理方法说成自己做过的项目经历。",
        "每道题都附编号与版本。更新题库后重新导出；旧文档保留导出当时的题目和答案。",
        "支持 HTML 折叠的 Markdown 阅读器中，答案默认收起。纯文本阅读器会显示全部内容。", "",
    ]
    if not header:
        output = ['']
    category = None
    for index, q in enumerate(questions, start + 1):
        if q["category"] != category:
            category = q["category"]
            output.extend(["## " + category, ""])
        output.extend([
            f"### {index}. {q['title']}", "",
            f"编号：`{q['id']}`　版本：`{q.get('version', 1)}`　强度：L{q.get('level', 1)}", "",
            q.get("body", ""), "",
            "<details>", "<summary>展开口述参考答案</summary>", "",
            q["answer"], "",
        ])
        if q.get("references"):
            output.extend(["核对资料：" + " · ".join(f"[资料 {i}]({u})" for i, u in enumerate(q["references"], 1)), ""])
        output.extend(["</details>", "", "我的表达 / 补充：", "", "---", ""])
    return "\n".join(output)
