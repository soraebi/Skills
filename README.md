# Skills

AI コーディングエージェント向けの自作スキル集。対象エージェントのランタイム毎にディレクトリを分けており、各ディレクトリはそのランタイムのスキルフォルダと 1:1 で対応します。インストールはコピー1回で完了します:

| ディレクトリ | ランタイム | インストール先 |
|---|---|---|
| [`Codex/`](Codex/) | [Codex](https://developers.openai.com/codex)(CLI / アプリ) | `${CODEX_HOME:-$HOME/.codex}/skills/` |
| [`Claude/`](Claude/) | [Claude Code](https://claude.com/claude-code) | `~/.claude/skills/` |

スキルは各エージェントのスキル形式・組み込みツール・呼び出し規約に依存するランタイム固有の成果物であり、ランタイム間での流用はできません。

## カタログ

| スキル | ランタイム | カテゴリ | 概要 |
|---|---|---|---|
| [sprite-gen](Codex/sprite-gen/) | Codex | ゲーム / 画像生成 | エンジン非依存のゲームキャラ用アニメーションスプライトシート生成(ピクセルアート/高解像度の2モード、状態・等身のコンフィグ駆動、TexturePacker 形式+Phaser/PixiJS 対応エクスポート)。[openai/skills の hatch-pet](https://github.com/openai/skills/tree/main/skills/.curated/hatch-pet) のフォーク。 |

## ライセンス

各スキルのディレクトリ内に別途記載がない限り、[MIT License](LICENSE) を適用します。上流プロジェクトからフォークしたスキルは元のライセンスと帰属表示を維持しています(例: `Codex/sprite-gen` は Apache License 2.0 — 同ディレクトリの `LICENSE.txt` / `README.md` を参照)。
