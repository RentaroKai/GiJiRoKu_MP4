# AI議事録作成アプリ（GiJiRoKu_MP4）

会議や講演の**動画ファイル**から自動的に議事録を作成するAI議事録君です
(Meeting Minutes App)

## 🌟 主な機能

- **動画ファイル**から会話内容を書き起こして議事録を作る
- 議事録まとめの自動生成（カスタマイズ可能）
- **話者の顔が映っている動画**（例: ZoomやTeamsの録画）を使用すると、話者の区別がより正確になり、精度の高い議事録を作成できます（実験的な機能）。

## 🚀 かんたん使い方

#### Step 1: ダウンロード
https://github.com/RentaroKai/GiJiRoKu_MP4/releases/

#### Step 2: 起動
1. 「GiJiRoKu.exe」をダブルクリックして起動
　※初回起動時、Windows Defenderのスマートスクリーン警告が表示される場合があります。その場合は「詳細情報」をクリックし、「実行」ボタンを選択してください。
2. 初回起動時は、APIキーの設定が必要です（詳しくは後述）

#### Step 3: ファイル選択
1. 「ファイル選択」ボタンをクリック
2. 議事録にしたい**動画ファイル**を選択
   - 対応形式：**動画（mp4, mkv, avi, mov, flvなど）**

#### Step 4: 実行
1. 必要に応じてオプションを外せる
   - 「議事録作成」: AIによる議事録まとめの生成
2. 「実行」ボタンをクリック

#### Step 5: 結果確認
作成された議事録は自動的に保存され、📁 ボタンで確認できます


## 🔑 APIキーの設定

このアプリは**Google APIキー (Gemini)** が必要です。

### Google APIキー
1. [GoogleのAI Studio](https://aistudio.google.com/app/apikey)でAPIキーを作成
2. 作成したAPIキーをアプリ→設定→GeminiAPIKeyに入力→保存。
または環境変数「GOOGLE_API_KEY」に設定

## ⚙️ 設定画面の使い方

設定ボタンから開く設定画面では、議事録作成の細かい部分をカスタマイズできます。

### 📝 基本設定タブ

#### APIキー設定
- **Google APIキー**: Gemini方式を使用する場合に必要

#### 処理設定
- **AIモデル**: 使用するGeminiのモデルを選択できます (例: `gemini-2.5-pro-exp-03-25`, `gemini-2.0-flash`)
- **話者置換処理を有効にする**: チェックを入れると、書き起こし時に話者を区別しようと試みます (実験的な機能)

- **分割処理用の秒数**: 長い音声を処理するための分割単位（推奨：300秒）
- **出力ディレクトリ**: 議事録の保存先

### 📋 議事録内容のカスタマイズ

「議事録の内容を指定」タブでは、AIに指示するプロンプトを自由に編集できます。
これにより、議事録に含めたい内容や形式を細かく指定できます。

- **議事録生成プロンプト**: どのような議事録を作成するか、AIへの指示内容
- **リセットボタン**: デフォルトのプロンプトに戻す

## ⚠️ 注意事項
- インターネット接続が必要です
- Googleの無料APIキーは学習に使われるため、機密性の高い情報を扱う場合は有料APIキーのご利用を推奨します。
- デフォルトのモデル"gemini-2.5-pro-exp-03-25"は利用上限が低いのと、動画解析能力が低く話者推定ができないので、本格的に使いたい場合は、有料課金して、設定で"gemini-2.5-pro-preview-03-25"に変更してください。
- 音声認識は100%正確ではありません。重要な会議では内容を確認してください


## 🛠️ Pythonを使う場合のカスタマイズのやり方

### プロンプトファイルの直接編集
`src/prompts/` ディレクトリ内の以下のファイルを直接編集することもできます：

- `minutes.txt`: 議事録の作成方法と形式
- `reflection.txt`: 会議の振り返り分析の基準
- `transcriptionGEMINI.txt`: 音声の書き起こし整形ルール

### AIモデルの変更
`settings.json`ファイルでGeminiモデルの種類などを変更できます：
アプリ初回起動時に自動的に作成される設定ファイルを編集するか、アプリ内の設定画面から変更できます。

## 🔧 必要要件

- Windows 10以上
- Python 3.9以上（exeファイルを使用する場合は不要）

## 📦 必要なパッケージ

詳細は requirements.txt をご確認ください

## 🛠️ ビルド方法

```bash
pyinstaller GiJiRoKu_MP4.spec
```

## 📝 ライセンス情報

### GiJiRoKu_MP4
MIT License

### FFmpeg
このソフトウェアは、FFmpeg（https://ffmpeg.org/）を使用しています。
FFmpegは以下のライセンスの下で提供されています：

- GNU Lesser General Public License (LGPL) version 2.1以降
- GNU General Public License (GPL) version 2以降

FFmpegのソースコードは以下から入手可能です：
https://ffmpeg.org/download.html

FFmpegは以下の著作権表示が必要です：
```
This software uses code of FFmpeg (http://ffmpeg.org) licensed under the LGPLv2.1 and its source can be downloaded from https://ffmpeg.org/
```
