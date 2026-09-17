# RDH が発行する gh コマンドの完全な一覧

**対象読者**: token をエージェントから隔離する仕組み（broker・proxy・許可リスト）を作る人。

RDH が GitHub に対して行う操作は、すべて下の許可リストに収まります。**推測ではなく実測です**。各 `rh` コマンドを fake `gh` 上で実行し、発行された argv をログから採取しました。さらに下のブロックは `tests/integration/test_gh_surface.py` が読み取り、実装が発行する gh 呼び出しと照合します。**文書と実装がずれるとテストが落ちます。**

## 許可リスト

```text rh-gh-surface
--version
auth status
repo view: --json
issue create: --title --body-file --label --repo
issue view: --json --repo
issue list: --state --limit --json --repo
issue comment: --body-file --repo
issue close: --comment --repo
pr create: --title --body-file --head --base --draft --repo
pr view: --json --repo
pr list: --head --state --limit --json --repo
pr edit: --body-file --repo
```

位置引数は、Issue 番号・PR 番号・branch 名（`pr view` の参照先）と、`repo view` の `owner/name` だけです。

## `rh` コマンドごとの gh 呼び出し

| rh コマンド | 発行する gh |
|---|---|
| `rh doctor` | `--version`、`auth status` |
| `rh status` / `rh resume` | `--version`、`issue view`、`pr view` |
| `rh ready` | `issue view`、`pr view` |
| `rh work link` | `issue view` |
| `rh rq create` / `rh issue create` | `issue create` |
| `rh record *` / `rh sync` | `issue view`（重複 UUID の確認）、`issue comment` |
| `rh work start` | `issue view`、`repo view`、`pr list`（新規 branch の PR 作成は遅延。下記） |
| `rh pr create` | `issue view`、`repo view`、`pr list`、`pr create` |
| `rh pr update` | `pr edit` |
| `rh issue close` | `issue view`、`issue close` |
| `rh log` | `issue list`、`issue view` |
| `rh rq list` | `issue list` |
| `rh rq show` | `issue list`、`issue view`、`pr list` |
| `rh audit` | `--version`、`issue list`、`pr list` |

`rh context` / `rh version` / `rh adopt` / `rh upgrade` は gh を叩きません。`rh sync` は outbox が空なら何も叩きません。

## 拒否した場合の影響

| gh | 拒否すると |
|---|---|
| `issue view` | **中核が止まる。** durable record（Issue comment）を読めず、record の投稿も重複確認で失敗する |
| `issue comment` | record を GitHub に届けられない（outbox に退避され続ける） |
| `issue create` | `/rh-scope` が Work Issue / Research Question を作れない |
| `pr create` | `/rh-start` が Draft PR を開けない |
| `pr edit` | `/rh-finish` が PR 本文を合成できない |
| `pr view` / `pr list` | state 導出が PR を認識できず、`rh ready` が「PR が無い」と判定する |
| `issue list` | `rh log` / `rh rq` が作業単位を列挙できない |
| `issue close` | 実験系の Work Issue を閉じられない |
| `repo view` | 既定 branch を推定できず、local の branch 検出に fallback する |
| `--version` | `rh doctor` が gh を ERROR と判定し、`rh audit` が GitHub 側の一覧を省略する |
| `auth status` | `rh doctor` の認証確認が WARNING になるだけ |

## subcommand を許可するだけでは足りない

**1. `--body-file` で読めるパスを制限すること。** RDH は本文を必ず `<repo>/.git/research-harness/tmp/` に書いてからパスを渡します（テストで固定）。broker が任意のパスを読むと、エージェントが `issue comment 2 --body-file ~/.ssh/id_ed25519` と渡すだけで、**token を見ないまま秘密を Issue に投稿できます**。読めるパスは上記ディレクトリに限定してください。

**2. `--repo` を固定すること。** `.research-harness/config.toml` の `github.repo` を設定すると、RDH は repo-scoped な全呼び出しに同じ `--repo` を付けます（テストで固定）。broker 側でもその値以外を拒否してください。固定しないと、token の権限が及ぶ別 repo に書き込めます。

**3. `repo view` だけは `--repo` を取りません。** `gh repo view` は `--repo` を受け付けず（`unknown flag`）、repository を位置引数で取ります。broker が「`--repo` が付いていること」を条件にすると、ここで弾いてしまいます。

**4. `issue close --comment` は本文が argv に載ります。** `gh issue close` に `--body-file` が無いためです。broker が argv をログに残すなら、ここだけ本文も残ります。

## 許可すべきでないもの

| gh | 理由 |
|---|---|
| `api` | **任意の GitHub API を token 付きで叩ける。** 許可すると隔離の意味が無くなる。RDH は使わない（fake `gh` は呼ばれると exit 99 で失敗する） |
| `auth token` / `auth status --show-token` | token そのものを表示する |
| `issue edit` | Work Issue 本文（当初の intent と `rh:work` marker）を書き換えられる。RDH が意図的に持たない操作（SPEC 29） |
| `pr comment` | PR comment は record store にしない（SPEC 25）。record を PR に書く誤用の入口になる |
| `pr merge` | RDH は merge しない。`READY_TO_MERGE` が終端 |

## gh の外にあるもの

**`git push`**。`rh work start` は branch を push します。これは gh の token ではなく git 側の認証を使います。HTTPS remote で gh を credential helper にしている場合、**token が git プロセス（エージェント側）に渡る**ので、隔離の目的に反します。push も broker 経由にするか、repo 限定の SSH deploy key を使ってください（ただし鍵ファイル自体はエージェントから読めます）。

**新規 branch の Draft PR は遅延されます。** GitHub は commit の無い branch に PR を作れないため、`rh work start` は PR を開かず、最初の commit の後に `rh pr create` で開きます。

## 検証の記録

- **2026-09-17**: record の読み出しを `gh api --paginate` から `gh issue view --json comments` に切り替える前に、実 GitHub 上で comment 105 件の Issue を作り、両者が同じ 105 件を同じ順序・重複なしで返すことを確認した（開発 repo の Issue #5）。100 件でページングが打ち切られることはない。
- 各 `rh` コマンドの gh 呼び出しは、`tests/fixtures/fake_gh.py` の呼び出しログから採取した。
