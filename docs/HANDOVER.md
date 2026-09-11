# 引継書 — Research Development Harness v0.1.0

最終更新: 2026-09-11 / runtime 0.1.0 / bundle 0.1.0 / record schema 1

このファイルは、**このプロジェクトを次に触る人（または次の Agent session）**
向けの引継ぎです。何が出来ていて、何が意図的にそうなっていて、何が欠けて
いるかを、判断の理由ごと残します。仕様は [SPEC.md](SPEC.md)、実装判断は
[IMPLEMENTATION.md](IMPLEMENTATION.md)、検証根拠は [ACCEPTANCE.md](ACCEPTANCE.md)。

---

## 1. いまの状態

- **v0.1.0**、335 tests green、standard library のみ（pytest 不要）。
- 実物の GitHub に対する live E2E 済み。fake `gh` だけでは見つからない不整合を 2 件、そこで発見して修正した。
- **実運用実績はゼロ。** テストしたシナリオは、すべて実装者が想像したもの。

```bash
./run-tests -q          # 全テスト（約 3〜4 分）
./bin/rh doctor         # この repo 自身の診断（distribution mode）
```

---

## 2. 壊してはいけない不変条件

改修時にここを侵していないか、必ず確認すること。**すべてテストで固定されている**ので、破ると落ちる。落ちたときに「テストのほうを直す」誘惑に注意すること。それが正しい場合もあるが、まず不変条件のほうを疑う。

| 不変条件 | 守っている場所 | 破った場合に落ちるテスト |
|---|---|---|
| `$HOME` に一切書かない | 設計全体 | `integration.test_home_zero_touch`（canary 3 本付き） |
| 破壊的 Git 操作を実行しない | `git.assert_safe_git` | `unit.test_safety`（禁止 30 種） |
| `adopt` は allow-list 外に書かない | `adopt.assert_allowed` | `integration.test_adoption` |
| AGENTS.md / CLAUDE.md は marker 内側のみ | `managed.py` | `unit.test_managed_and_config` |
| Skill は thin adapter のまま | `bundle/*-skills/` | `unit.test_skill_bundle` |
| Skill frontmatter は `name` と `description` だけ | 同上 | 同上（他 vendor で invalid になる） |
| record は追記のみ、過去を書き換えない | `github.py` に edit 系を置かない | — （wrapper 自体を削除済み） |
| CLI に科学的判断を入れない | `state.py` / `cli.py` | — （設計判断。レビューで守る） |
| merge しない | `github.py` に merge 系なし | fake gh が `pr merge` で exit 99 |

---

## 3. すでに決めたこと（蒸し返さない）

| 決定 | 理由 |
|---|---|
| **hook は実装しない** | 2026-09-11 にユーザー判断。技術的には project-local hook（`.claude/settings.json` / `.codex/hooks.json`）で `$HOME` を汚さず実現可能だが、deployment contract の拡張と JSON の構造 merge が要る。必要になったら opt-in（`rh adopt --with-hooks`）で。 |
| **専用の uninstall コマンドを作らない** | allow-list 領域にしか書かないので `git revert` が機能する。実測確認済み。 |
| **`rh log` は横断、`rh resume` は深掘り** | 役割を混ぜない。`log` を `resume` の代用にしない旨を workflow に明記済み。 |
| **`rq show` は結論を合成しない** | Result Record の記述を原文のまま並べるだけ。問いへの答えは研究者が決める。 |
| **完了は宣言による** | gate が残っていないことは終わった証拠ではない。`--phase review` の宣言でのみ `READY_TO_MERGE` に到達する。 |
| **記録は Work Issue comment のみ** | PR comment は record store にしない（SPEC 25）。そのための wrapper も置かない。 |

---

## 4. この作業で学んだこと（次も同じ罠がある）

**fake `gh` は実 API と食い違う。** 2 件やられた。

1. GitHub は **commit が無い branch に PR を作れない** — `rh work start` が新規 branch を作った直後は、まさにその状態。fake は作れてしまっていた。
2. `gh repo view` は **`--repo` を受け付けない**（位置引数）。付けていたので `default_branch()` が常に失敗し、黙って `None` を返していた。エラーも出ず、local fallback で動いて見えていた。

→ **fixture の忠実性を疑うこと。** 両方とも fake 側を実挙動に合わせて修正済み。新しい `gh` 呼び出しを足したら、可能な範囲で live で 1 回叩くこと。

**ドキュメントを書くとバグが出る。** README の実例を現行コードで再現し直したら、`IN_PROGRESS` が evidence 系の作業で到達不能になっていることが判明した（`VALIDATING` を「evidence gate が pending なら」で返していた）。

→ **README の出力例は必ず実際に採取すること。** 手で書いた例は嘘になるし、嘘を書いた瞬間に実装の誤りが見えなくなる。採取用スクリプトは `tests/support.py` の `Sandbox` がそのまま使える。

**テストが現実に起こり得ない前提を書いていることがある。** PR 遅延を実装したら 17 件落ちたが、全部「commit 無し branch に PR が作れる」前提だった。

---

## 5. 欠けているもの（優先度順）

| # | 欠落 | 状況 |
|---|---|---|
| 1 | **`DEFERRED` / `ABANDONED` に CLI 経路が無い** | Issue の `rh:work` marker を手で編集するしかない。「この筋は一旦保留」は研究では日常的なので、`rh work defer <n>` / `abandon <n>` があるべき。README の状態表に注記済み。 |
| 2 | **live E2E が自動化されていない** | 手動実行のみ。`tests/e2e/` に、明示的な test repository 環境変数で gate する形が想定されている。通常 CI は GitHub account 不要のまま保つこと。 |
| 3 | **規模が未検証** | Issue 数十を超えると `rh log` / `rq show` の API 呼び出しが線形に増える。`--limit-issues` の既定値 100 の妥当性も未検証。 |
| 4 | **concurrency lock が未実装** | `.git/research-harness/lock/` は SPEC 56 で予約されているだけ。同一 branch の並行書き込みは文書で禁じているのみ。 |
| 5 | **record の訂正手段が無い** | append-only は正しいが、誤った Result Record を撤回できない。後続 record が先行を無効化する `supersedes: <uuid>` が筋。 |
| 6 | **権限・保護された repo が未検証** | branch protection、write 権限なし、rate limit 下。 |

---

## 6. 触るときの手順

**実装を変えたら**: `./run-tests -q`。テスト数が変わったら README 末尾と `docs/ACCEPTANCE.md` の数値も直す（両方に書いてある）。

**`gh` 呼び出しを足したら**: `tests/fixtures/fake_gh.py` に対応を足し、**実 API でも 1 回叩く**。`GitHubClient._NO_REPO_FLAG` に注意（`--repo` を受けないサブコマンドがある）。

**CLI を足したら**: README 第 7 節の表、該当する `bundle/workflows/*.md`、`CHANGELOG.md`。文書と実装の突き合わせは、コマンドとフラグを argparse から抜いて grep する使い捨てスクリプトで機械的に確認できる。

**README の例を更新するときは**: 必ず `tests/support.py` の `Sandbox` で実際に流して採取する。作文しない。

**live E2E をやるとき**: 実 repo を clone → `./bin/rh adopt <clone>` → `.git/info/exclude` に adoption 成果物を入れて PR を汚さない、という手順が使える。

---

## 7. GitHub 上に残してあるもの

live E2E の成果物。確認用に開いたままなので、不要なら close してよい（削除は不要）。

- Issue [#1](https://github.com/Lzh-Function/research-development-harness/issues/1) — RQ（`rh:rq` marker の実例）
- Issue [#2](https://github.com/Lzh-Function/research-development-harness/issues/2) — Work Issue、durable record 7 件が実際に載っている
- PR [#3](https://github.com/Lzh-Function/research-development-harness/pull/3) — Draft のまま（**RDH が merge しないことの実物の証拠**）
- branch `rh/2-live-e2e-full-work-lifecycle-against-real-github`
- Issue #4 は close 済み（close precondition の確認用）

**この repo 自身は RDH に self-adopt していない。** SPEC 66 の想定どおり dogfooding は可能な段階にあるが、まだやっていない。

---

## 8. 使い始めるときの助言

初めて実プロジェクトに入れるなら:

1. **過去を移行しない。** Overlay + Cutover。README 第 6 節のとおり。
2. **1 つの work unit で 2 週間。** 全 branch を一斉に追跡しない。
3. **gate の閾値を最初から緩めない。** `config.toml` の既定のまま。
4. **`baseline.md` を埋める。** 放置すると adopt の価値が半減する。

2 週間後、`/rh-resume` だけで翌日の作業に戻れているか、`rh log --kind result` が使えるか、Deviation Gate で「危なかった」と思う場面があったか、を見ること。どれも無いなら、緩めるか `git revert` で戻す。**合わなかったという結論も正しい結論。**
