# sprite-gen

**エンジン非依存のゲームキャラ用アニメーションスプライトシート**を生成する [Codex](https://developers.openai.com/codex) スキル。テキストコンセプト・ブランドキュー・参照画像から、Codex 組み込みの画像生成と決定論的な Python パイプライン(フレーム抽出・アトラス合成・検証・視認QA)でスプライトシートを作成します。

[openai/skills](https://github.com/openai/skills) の [`hatch-pet`](https://github.com/openai/skills/tree/main/skills/.curated/hatch-pet) をフォークし、Codex アプリ固定のペット契約(8×9 グリッド・192×208 セル・9状態固定)を完全コンフィグ駆動のスプライトパイプラインへ一般化したものです。

## 特徴

- **コンフィグ駆動のアニメーション仕様**: 状態・フレーム数・フレーム毎の表示時間・アトラスグリッド・セルサイズを解決済みスペック(`sprite_request.json`)で一元管理 — 全スクリプトの単一情報源
- **2つのレンダーモード**: `pixel`(16/32/64px 等の論理ピクセルサイズ。高解像度で生成し、グローバルパレットで決定論的にピクセライズ)と `hires`
- **等身の選択**: `chibi-2` / `toon-3` / `semi-5` / `realistic-7`(頭身比がプロンプトとセル縦横比の既定値に反映)
- **ゲーム向けアンカリング**: bottom-center アンカー+ベースライン安定のフレーム抽出(ゲーム内でのジッタを防止)
- **ミラー派生**: `walk-left` を `walk-right` のフレーム単位ミラーとして宣言可能(時間順序を保持・明示承認ゲート付き)
- **エンジン非依存のエクスポート**: `spritesheet.png/webp` + TexturePacker hash 形式の `spritesheet.json`(Phaser / PixiJS でそのまま読込可)+ `animations.json`(状態毎のフレーム・表示時間・ループフラグ・アンカー)+ 任意で状態別ストリップと整数拡大 `@Nx` ペア
- **同梱プリセット**: `minimal` / `side-scroller` / `rpg-4dir` / `codex-pet` に加え、ゲームキャラのアニメーションで頻出する動作を一通りカバーする `platformer-hero` / `combat-actions` / `platformer-moves`(詳細は下表)
- **QAと修復ループ**: コンタクトシート・状態別GIFプレビュー・決定論的検証・最小スコープの行単位修復

## 同梱プリセット一覧

imagegen ジョブ数 = 状態数 + 1(base)。`combat-actions` と `platformer-moves` は `platformer-hero` と同じ hires/192×208/toon-3 なので、同一キャラの主人公動作を分割して生成する追加セットとして組み合わせる想定です。

| プリセット | 用途 | モード/セル/等身 | 状態(フレーム数) | ジョブ数 |
|---|---|---|---|---|
| `minimal` | 動作確認・使い捨てNPC | pixel 32px / chibi-2 | idle(4), walk-right(6) | 3 |
| `side-scroller` | 横スクロールアクションの基本セット | hires 192×208 / toon-3 | idle(4), run-right(8), run-left(8, mirror), jump(5), attack(5), hurt(3), death(6) | 7 |
| `rpg-4dir` | トップダウンRPGの4方向移動 | pixel 32px / toon-3 | idle-down(2), walk-down(4), walk-up(4), walk-right(4), walk-left(4, mirror) | 6 |
| `codex-pet` | hatch-pet(Codexアプリ固定ペット契約)との回帰確認専用 | hires 192×208 / chibi-2 | 9状態(hatch-petと同一幾何) | 10 |
| `platformer-hero` | 横スクロールアクション主人公のフルセット | hires 192×208 / toon-3 | idle(4), run(6), jump(3), fall(3), attack(5), hurt(3), death(6) | 8 |
| `combat-actions` | 戦闘動作の追加セット(コンボ・遠距離・魔法・防御・回避) | hires 192×208 / toon-3 | attack-combo(8), shoot(4), cast(6), block(2), dodge(4) | 6 |
| `platformer-moves` | 移動バリエーションの追加セット | hires 192×208 / toon-3 | crouch(2), climb(4), dash(4), land(3), wall-slide(2) | 6 |

## 動作要件

- Codex CLI / Codex アプリ(`$imagegen` システムスキルが利用可能であること)
- Python 3.10+ と [Pillow](https://pypi.org/project/pillow/)(同梱 `scripts/` 用。`uv run --with pillow python ...` などランチャーは任意)
- `jq`(`SKILL.md` に記載のジョブマニフェスト処理で使用)

## インストール

このディレクトリを Codex のスキルフォルダにコピーしてください:

```text
${CODEX_HOME:-$HOME/.codex}/skills/sprite-gen/
```

その後、Codex に次のように依頼します: 「sprite-gen で横スクロール用キャラを作って: 陽気な苔グリーンのスライム騎士、pixel モード、32px、チビ等身」

## ドキュメント

- `SKILL.md` — Codex が従うワークフロー全体(生成委譲・ワーカープロンプト・修復ループ・パッケージング)
- `references/spec-format.md` — スペックのスキーマとプリセット作成ガイド
- `references/output-formats.md` — エクスポートファイル形式と Phaser/PixiJS の読込スニペット
- `references/qa-rubric.md` — 視認QAのルーブリック

## ライセンス

Apache License 2.0(`LICENSE.txt` 参照)。本スキルは [openai/skills](https://github.com/openai/skills) の `hatch-pet` を改変したフォークです。主な変更点: コンフィグ駆動のスペックシステム(`scripts/spec_lib.py`)、ピクセルアートパイプライン(`scripts/pixelize_frames.py`)、エンジン非依存エクスポータ(`scripts/export_spritesheet.py`)、ミラー派生の一般化、スキル/リファレンスドキュメントの全面書き直し。
