"""Independently written Q&A, checked against the linked primary references.
Original supplied translations remain unchanged in the pending source archive.
"""
DATA = [
    ("git-tracked", "git", "Git", "如何可靠判断 config.yaml 是否已被 Git 跟踪，并跟踪一个未跟踪文件？",
     "在仓库内执行 `git ls-files --error-unmatch -- config.yaml`；匹配索引中的文件时成功，找不到匹配时返回非零。单用 `git ls-files config.yaml` 没有输出不能靠退出码 0 判断已跟踪。确认不是路径/仓库错误后，用 `git add -- config.yaml` 暂存文件，再看 `git status --short`。对被忽略的文件先核实忽略规则，不要盲目强制添加。",
     ["https://git-scm.com/docs/git-ls-files", "https://git-scm.com/docs/git-add"]),
    ("git-merge", "git", "Git", "普通 git merge 因冲突暂停后，怎样继续合并？",
     "用 `git status` 查看未合并文件，编辑并消除冲突，验证最终内容和测试。对解决后的文件 `git add -- 文件名`；删除的文件可用 `git rm -- 文件名`。然后 `git merge --continue`（也可提交合并提交）。`git rebase --continue` 只用于正在进行的 rebase，不能当作普通 merge 的后续命令。放弃本次合并可用 `git merge --abort`，合并前应先保存未提交工作。",
     ["https://git-scm.com/docs/git-merge"]),
    ("git-untrack", "git", "Git", "怎样从 Git 索引移除已跟踪文件，同时保留工作区文件？",
     "确认没有需要保留的暂存差异后，用 `git rm --cached -- config.yaml`，提交这次索引删除；工作区文件仍在。如后续也不应跟踪，给 `.gitignore` 添加规则并提交。`git rm` 不带 `--cached` 默认也删除工作区文件；`git reset -- 文件` 只是重置暂存状态，不能代替停止跟踪。已提交过的秘密不会因此从历史中消失。",
     ["https://git-scm.com/docs/git-rm", "https://git-scm.com/docs/gitignore"]),
    ("git-delete-remote", "git", "Git", "如何删除 origin 上的 feature/demo 分支？",
     "先确认目标分支可删除，然后执行 `git push origin --delete feature/demo`。这是请求删除远端分支，本地同名分支不会随之自动删除；受保护分支可能被服务端拒绝。需要查看远端实际分支时可用 `git ls-remote --heads origin`。",
     ["https://git-scm.com/docs/git-push"]),
    ("tls13-handshake", "network", "网络与 DNS", "TLS 1.3 的首次证书认证握手大致如何进行？（不讨论 PSK、0-RTT 与重试）",
     "客户端发 ClientHello，携带版本、密码套件和密钥份额等；服务端 ServerHello 选择参数并给出密钥份额。双方通过密钥协商与 HKDF 派生握手密钥。服务端再发加密的 EncryptedExtensions、Certificate、CertificateVerify 和 Finished。客户端验证证书链、名称、有效期及签名/Finished 后发自己的 Finished，随后以派生的应用流量密钥保护数据。TLS 1.3 不是客户端用服务器 RSA 公钥加密 premaster secret 的旧式 RSA 密钥传输流程。",
     ["https://www.rfc-editor.org/rfc/rfc8446.html"]),
    ("ipv6-encryption", "network", "网络与 DNS", "IPv6 地址变成 128 位之后，通信是否就自动加密了？",
     "不会。IPv6 提供更大的地址空间，IPv4 地址为 32 位，IPv6 地址为 128 位。地址长度和是否加密是不同问题；使用 IPv6 不会自动启用 IPsec，也不会自动配置身份认证与密钥。应按需要配置 TLS 或 IPsec 等机制，并继续维护防火墙与访问控制。IPv6 节点规范对 IPsec 支持的建议不能解读为所有 IPv6 流量已加密。",
     ["https://www.rfc-editor.org/rfc/rfc8200.html", "https://www.rfc-editor.org/rfc/rfc8504.html"]),
]


def questions():
    return [{
        "id": "verified-" + slug, "module": module, "category": category,
        "title": title, "answer": answer, "body": "用自己的话解释，并指出命令或协议适用的前提。",
        "source": "OpsForge 独立编写 · 官方资料核对", "references": refs,
        "type": "interview", "level": 2, "version": 1, "has_answer": True,
        "review_status": "reviewed", "review_note": "已核对所列官方文档；Git 索引相关命令另有本地仓库验证。",
        "hints": ["区分操作对象与使用前提。"], "rubric": ["概念与操作一致", "指出限制"],
    } for slug, module, category, title, answer, refs in DATA]
