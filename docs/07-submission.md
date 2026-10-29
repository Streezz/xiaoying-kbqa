# 提交与推送

当前仓库 origin 为 https://github.com/Streezz/xiaoying-kbqa.git，分支为 main。以下是可执行步骤，本次修改未自动 commit 或 push。

## 1. 验证

Windows PowerShell：

```powershell
Set-Location 'D:\BaiduNetdiskDownload\aii\xiaoying'
.\.venv\Scripts\python.exe -X utf8 -m pytest -v
.\.venv\Scripts\python.exe -X utf8 -m kbqa eval --mode replay
.\.venv\Scripts\python.exe -X utf8 -m kbqa.verify_regressions --mode replay
git diff --check
git status --short
```

每一步应通过再继续。查看 docs/03-evaluation.md 中的真实验证边界，不用删除失败历史来让结果显得更好。

## 2. 检查并提交

```powershell
git add -- src/kbqa tests docs examples README.md .env.example
git diff --cached --stat
git diff --cached --name-only
git commit -m "fix: validate grounded answers and strengthen KBQA evaluation"
```

原工作区已有未跟踪的 .gitattributes（统一 LF 换行）。如果本次也要纳入它，可在 commit 前执行 git add -- .gitattributes。本次未改写该文件。

.env、var/、虚拟环境不应出现在暂存列表。仓库外的 xiaoying-review-notes/ 保存原始问题快照，不在上述提交范围内。

## 3. 同步并推送

```powershell
git fetch origin
git status -sb
git log --oneline HEAD..origin/main
```

若最后一条无输出，直接推送：

```powershell
git push origin HEAD:main
git rev-parse HEAD
```

若远端已有新提交，先在本地提交完成且工作区清洁的情况下同步：

```powershell
git rebase origin/main
```

发生冲突时先解决、重新验证，再执行 git rebase --continue；取消同步可用 git rebase --abort。同步完成后普通 push 即可，不需要强推。

提交表填写：题号 3、上述 GitHub URL、git rev-parse HEAD 的完整输出。不要使用本次修改前的旧 SHA。
