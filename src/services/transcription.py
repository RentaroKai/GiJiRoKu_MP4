import os
import pathlib
import logging
import datetime
import json
from typing import Dict, Any, Literal
from ..utils.new_gemini_api import GeminiAPI, GeminiAPIError as TranscriptionError
import sys
# from ..modules.audio_splitter import AudioSplitter
from pathlib import Path
import re
from ..utils.ffmpeg_handler import split_media_fixed_duration

logger = logging.getLogger(__name__)

def add_speaker_identifier(text, identifier):
    """
    文字起こしテキスト内の話者名に識別子を付加する

    Args:
        text (str): 元の文字起こしテキスト
        identifier (str): 付加する識別子 (例: "seg1")

    Returns:
        str: 話者名に識別子が付加されたテキスト
    """
    # テキストがJSON形式かを確認
    try:
        # JSONとして解析を試みる
        if text.strip().startswith('{') or text.strip().startswith('['):
            data = json.loads(text)

            # JSONオブジェクトの場合
            if isinstance(data, dict):
                if "speaker" in data:
                    data["speaker"] = f"{data['speaker']}_{identifier}"
                # 会話リストを含む場合
                if "conversations" in data and isinstance(data["conversations"], list):
                    for conversation in data["conversations"]:
                        if isinstance(conversation, dict) and "speaker" in conversation:
                            conversation["speaker"] = f"{conversation['speaker']}_{identifier}"

            # JSON配列の場合
            elif isinstance(data, list):
                for item in data:
                    if isinstance(item, dict) and "speaker" in item:
                        item["speaker"] = f"{item['speaker']}_{identifier}"

            return json.dumps(data, ensure_ascii=False)
    except (json.JSONDecodeError, AttributeError):
        # JSONとして解析できない場合は通常のテキストとして処理
        pass

    # 通常のテキストの場合、正規表現で話者名を識別して置換
    # 一般的な話者パターン: "話者名:" や "話者名 :"
    text = re.sub(r'(話者\d+)\s*:', r'\1_' + identifier + ':', text)
    text = re.sub(r'(スピーカー\d+)\s*:', r'\1_' + identifier + ':', text)
    text = re.sub(r'(Speaker\s*\d+)\s*:', r'\1_' + identifier + ':', text)

    # 不正なJSONの場合でも話者名を識別して置換（JSONっぽい文字列の場合）
    if '"speaker"' in text:
        text = re.sub(r'"speaker"\s*:\s*"([^"]*)"', r'"speaker": "\1_' + identifier + '"', text)

    return text

class TranscriptionError(Exception):
    """書き起こし処理関連のエラーを扱うカスタム例外クラス"""
    pass

class TranscriptionService:
    def __init__(self, output_dir: str = "output/transcriptions", config_path: str = "config/settings.json"):
        self.output_dir = pathlib.Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        logger.info(f"出力ディレクトリを作成/確認: {self.output_dir}")

        # 実行環境の確認
        is_frozen = getattr(sys, 'frozen', False)
        logger.info(f"TranscriptionService初期化: 実行モード={'PyInstaller' if is_frozen else '通常'}")

        # PyInstallerモードでの設定ファイルパスの解決
        if is_frozen:
            exe_dir = pathlib.Path(sys.executable).parent
            alt_config_path = exe_dir / config_path
            if alt_config_path.exists():
                logger.info(f"PyInstaller実行モード: 代替設定ファイルを使用 - {alt_config_path}")
                config_path = str(alt_config_path)
            else:
                logger.warning(f"PyInstaller実行モード: 代替設定ファイルが見つかりません - {alt_config_path}")

        logger.info(f"使用する設定ファイルパス: {config_path}")

        # 設定の読み込み
        self.config = self._load_config(config_path)
        self.transcription_method = self.config.get("transcription", {}).get("method", "gemini")
        logger.info(f"書き起こし方式: {self.transcription_method}")

        # 再試行フラグの初期化
        self.has_reached_max_retries = False

        # Gemini APIの初期化（Gemini方式が選択されている場合）
        if self.transcription_method == "gemini":
            self.gemini_api = GeminiAPI()
            logger.info("Gemini APIを初期化しました")

        # プロンプトの読み込み
        if getattr(sys, 'frozen', False):
            # PyInstallerで実行している場合
            base_path = pathlib.Path(sys._MEIPASS)
            prompt_path = base_path / "src/prompts/transcription.txt"
            logger.info(f"PyInstaller実行モード - プロンプトパス: {prompt_path}")
        else:
            # 通常の実行の場合
            prompt_path = pathlib.Path("src/prompts/transcription.txt")
            logger.info(f"通常実行モード - プロンプトパス: {prompt_path}")

        if not prompt_path.exists():
            logger.error(f"書き起こしプロンプトファイルが見つかりません: {prompt_path}")
            logger.error(f"現在のディレクトリ: {os.getcwd()}")
            logger.error(f"ディレクトリ内容: {list(prompt_path.parent.glob('**/*'))}")
            raise TranscriptionError(f"書き起こしプロンプトファイルが見つかりません: {prompt_path}")

        try:
            logger.info(f"プロンプトファイルを読み込み中: {prompt_path}")
            with open(prompt_path, "r", encoding="utf-8") as f:
                self.system_prompt = f.read().strip()
            logger.info(f"プロンプトファイルを読み込みました（長さ: {len(self.system_prompt)}文字）")
        except UnicodeDecodeError as e:
            logger.error(f"プロンプトファイルのエンコーディングエラー: {str(e)}")
            # UTF-8で失敗した場合、CP932で試行
            try:
                with open(prompt_path, "r", encoding="cp932") as f:
                    self.system_prompt = f.read().strip()
                logger.info(f"CP932エンコーディングでプロンプトファイルを読み込みました（長さ: {len(self.system_prompt)}文字）")
            except Exception as e2:
                logger.error(f"CP932でも読み込みに失敗: {str(e2)}")
                raise TranscriptionError(f"プロンプトファイルの読み込みに失敗しました: {str(e)} -> {str(e2)}")
        except Exception as e:
            logger.error(f"プロンプトファイルの読み込み中にエラー: {str(e)}")
            raise TranscriptionError(f"プロンプトファイルの読み込みに失敗しました: {str(e)}")

    def _load_config(self, config_path: str) -> Dict[str, Any]:
        """設定ファイルから設定を読み込む"""
        try:
            logger.info(f"設定ファイルを読み込み開始: {config_path}")
            config_file = pathlib.Path(config_path)

            if not config_file.exists():
                logger.info("設定ファイルが見つかりません。デフォルトの設定を使用します。")
                default_config = {"transcription": {"method": "gemini"}}
                logger.info(f"デフォルト設定内容: {default_config}")
                return default_config

            try:
                logger.info(f"設定ファイルを読み込み中: {config_file} (サイズ: {config_file.stat().st_size} bytes)")
                with open(config_file, "r", encoding="utf-8") as f:
                    config_text = f.read().strip()
                    # 空ファイルチェック
                    if not config_text:
                        logger.warning("設定ファイルが空です。デフォルトの設定を使用します。")
                        default_config = {"transcription": {"method": "gemini"}}
                        logger.info(f"空ファイル時のデフォルト設定内容: {default_config}")
                        return default_config

                    # 文字列を整形して余分な文字を削除
                    config_text = config_text.replace('\n', '').replace('\r', '').strip()
                    # 最後のカンマを削除（一般的なJSON解析エラーの原因）
                    if config_text.endswith(',}'):
                        config_text = config_text[:-2] + '}'

                    logger.info(f"設定ファイル内容（処理後）: {config_text[:100]}...")
                    config = json.loads(config_text)
            except json.JSONDecodeError as e:
                logger.warning(f"設定ファイルのJSONパースに失敗しました: {str(e)}。デフォルトの設定を使用します。")
                default_config = {"transcription": {"method": "gemini"}}
                logger.info(f"JSONエラー時のデフォルト設定内容: {default_config}")
                return default_config
            except Exception as e:
                logger.warning(f"設定ファイルの読み込み中に予期せぬエラーが発生しました: {str(e)}。デフォルトの設定を使用します。")
                default_config = {"transcription": {"method": "gemini"}}
                logger.info(f"その他エラー時のデフォルト設定内容: {default_config}")
                return default_config

            method = config.get("transcription", {}).get("method", "gemini")
            logger.info(f"読み込まれた書き起こし方式: {method}")

            if method not in ["whisper_gpt4", "gpt4_audio", "gemini"]:
                logger.warning(f"無効な書き起こし方式が指定されています: {method}")
                logger.info("デフォルトの書き起こし方式 'gemini' を使用します。")
                config["transcription"]["method"] = "gemini"

            return config

        except Exception as e:
            logger.error(f"設定ファイルの処理中に予期せぬエラーが発生しました: {str(e)}")
            default_config = {"transcription": {"method": "gemini"}}
            logger.info(f"最終エラー時のデフォルト設定内容: {default_config}")
            return default_config

    def process_audio(self, audio_file: pathlib.Path, additional_prompt: str = "") -> Dict[str, Any]:
        """音声ファイルの書き起こし処理を実行"""
        try:
            logger.info(f"書き起こしを開始: {audio_file}")
            logger.info(f"音声ファイルサイズ: {audio_file.stat().st_size:,} bytes")
            logger.info(f"使用する書き起こし方式: {self.transcription_method}")

            # 再試行フラグをリセット
            self.has_reached_max_retries = False

            # タイムスタンプの生成
            timestamp = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
            logger.info(f"タイムスタンプ: {timestamp}")

            # 書き起こし処理の実行
            if self.transcription_method == "gemini":
                result = self._process_with_gemini(audio_file, timestamp)
            else:
                # gemini 以外の方式はサポートされていないためエラーとする
                logger.error(f"サポートされていない書き起こし方式です: {self.transcription_method}。Gemini方式を使用してください。")
                raise TranscriptionError(f"サポートされていない書き起こし方式です: {self.transcription_method}。Gemini方式を使用してください。")

            # 処理完了後、最大再試行回数に達したかどうかをチェックして通知
            if self.has_reached_max_retries:
                result["warning"] = "一部のセグメントで最大再試行回数に達しました。文字起こし結果にエラーが含まれている可能性があります。"
                logger.warning("警告: 一部のセグメントで最大再試行回数に達しました。文字起こし結果にエラーが含まれている可能性があります。")

            return result

        except Exception as e:
            logger.error(f"書き起こし処理中にエラーが発生しました: {str(e)}")
            raise TranscriptionError(f"書き起こしに失敗しました: {str(e)}")

    def _process_with_gemini(self, audio_file: pathlib.Path, timestamp: str) -> Dict[str, Any]:
        """Gemini方式での書き起こし処理"""
        logger.info("Geminiで音声認識・整形を開始")

        try:
            # 設定から分割長を取得（デフォルトは100秒）
            segment_length = self.config.get('transcription', {}).get('segment_length_seconds', 600)
            logger.info(f"設定された分割長: {segment_length}秒")

            # セグメント保存用の一時ディレクトリを作成
            segments_dir = self.output_dir / "segments" / timestamp
            segments_dir.mkdir(parents=True, exist_ok=True)
            logger.info(f"セグメント一時ディレクトリを作成: {segments_dir}")

            # ファイルの拡張子を取得（MP4等はそのまま使用）
            file_extension = audio_file.suffix.lower()
            is_video = file_extension in ['.mp4', '.avi', '.mov', '.mkv', '.webm']
            logger.info(f"入力ファイルタイプ: {'動画' if is_video else '音声'}, 拡張子: {file_extension}")

            # メディアファイルを分割（AudioSplitterを使わず、ffmpeg_handlerを使用）
            logger.info("メディアファイルの分割を開始")
            split_files = split_media_fixed_duration(
                str(audio_file),
                str(segments_dir),
                segment_length
            )
            logger.info(f"メディアを {len(split_files)} 個のセグメントに分割しました")

            # 各セグメントの文字起こし結果を保存
            all_transcriptions = []
            for i, segment_file in enumerate(split_files, 1):
                logger.info(f"セグメント {i}/{len(split_files)} の文字起こしを実行中...")

                # セグメントの文字起こし処理部分
                max_retries = 2  # 最大再試行回数
                segment_text = None

                for attempt in range(max_retries + 1):
                    try:
                        # 動画または音声ファイルをそのまま送信
                        segment_text_raw = self.gemini_api.transcribe_audio(str(segment_file))
                        # 文字起こし結果の余分な空白を除去
                        segment_text = re.sub(r'\s+', ' ', segment_text_raw).strip() if segment_text_raw else ""

                        logger.info(f"セグメント {i} の文字起こし結果: 文字数={len(segment_text)}")
                        logger.debug(f"セグメント {i} の文字起こし結果（先頭100文字）: {segment_text[:100]}...")

                        # 問題のあるパターンをチェック
                        logger.info(f"セグメント {i} の繰り返しパターンチェックを実行")
                        if segment_text and self.is_problematic_transcription(segment_text):
                            logger.warning(f"セグメント {i} で問題のあるパターンが検出されました")
                            if attempt < max_retries:
                                logger.warning(f"セグメント {i} に問題のあるパターンが検出されました。再試行します ({attempt+1}/{max_retries})")
                                continue
                            else:
                                logger.error(f"セグメント {i} の処理が最大再試行回数に達しました。最後の結果を使用します。")
                                self.has_reached_max_retries = True  # エラー表示のためのフラグ
                        else:
                            logger.info(f"セグメント {i} は正常なテキストと判断されました")
                        # 問題なければループを抜ける
                        break
                    except Exception as e:
                        logger.error(f"セグメント {i} の文字起こし中にエラー: {str(e)}")
                        if attempt < max_retries:
                            logger.warning(f"再試行します ({attempt+1}/{max_retries})")
                        else:
                            logger.error(f"最大再試行回数に達しました。このセグメントをスキップします。")
                            self.has_reached_max_retries = True  # エラー表示のためのフラグ
                            segment_text = ""

                if not segment_text:
                    logger.warning(f"セグメント {i} の文字起こし結果が空です")
                    continue

                # 話者名に識別子を付加 (セグメント番号を使用)
                segment_identifier = f"seg{i}"
                segment_text = add_speaker_identifier(segment_text, segment_identifier)
                logger.info(f"セグメント {i} の話者名に識別子 '{segment_identifier}' を付加しました")

                # セグメント情報を追加
                segment_result = {
                    "segment": i,
                    "segment_file": Path(segment_file).name,
                    "text": segment_text
                }
                all_transcriptions.append(segment_result)
                logger.info(f"セグメント {i} の文字起こしが完了")

            # 中間結果をJSONとして保存
            complete_result = {
                "metadata": {
                    "total_segments": len(split_files),
                    "original_file": str(audio_file)
                },
                "segments": all_transcriptions
            }

            complete_json_path = self.output_dir / f"complete_transcription_{timestamp}.json"
            with open(complete_json_path, "w", encoding="utf-8") as f:
                json.dump(complete_result, f, ensure_ascii=False, indent=2)
            logger.info(f"中間結果をJSONとして保存: {complete_json_path}")

            # 全セグメントの結果を結合
            combined_text = "".join(seg["text"] for seg in all_transcriptions)
            formatted_text = re.sub(r'\s+', ' ', combined_text).strip()
            formatted_text = re.sub(r'(?<=[\u3000-\u303F\u3040-\u309F\u30A0-\u30FF\u4E00-\u9FFF])\s+(?=[\u3000-\u303F\u3040-\u309F\u30A0-\u30FF\u4E00-\u9FFF])', '', formatted_text)

            # 最終結果を保存
            formatted_output_path = self.output_dir / f"transcription_summary_{timestamp}.txt"
            formatted_output_path.parent.mkdir(parents=True, exist_ok=True)

            try:
                with open(formatted_output_path, "w", encoding="utf-8") as f:
                    f.write(formatted_text)
            except Exception as e:
                logger.error(f"整形済みテキストの保存中にエラー: {str(e)}")
                raise TranscriptionError(f"整形済みテキストの保存に失敗しました: {str(e)}")

            # 生のテキストを保存（新APIの動作に合わせる）
            raw_output_path = self.output_dir / f"transcription_{timestamp}.txt"
            logger.info(f"生テキストを保存: {raw_output_path}")
            try:
                with open(raw_output_path, "w", encoding="utf-8") as f:
                    f.write(formatted_text)
            except Exception as e:
                logger.error(f"生テキストの保存中にエラー: {str(e)}")
                logger.warning("生テキストの保存に失敗しましたが、処理は続行します")

            # 一時ファイルのクリーンアップ
            try:
                import shutil
                shutil.rmtree(segments_dir)
                logger.info("一時ファイルのクリーンアップが完了しました")
            except Exception as e:
                logger.warning(f"一時ファイルのクリーンアップ中にエラー: {str(e)}")

            logger.info("Gemini方式での書き起こし処理が完了しました")
            return {
                "raw_text": formatted_text,
                "formatted_text": formatted_text,
                "raw_file": raw_output_path,
                "formatted_file": formatted_output_path,
                "timestamp": timestamp
            }

        except Exception as e:
            logger.error(f"Gemini方式での処理中にエラー: {str(e)}")
            raise TranscriptionError(f"Gemini方式での処理に失敗しました: {str(e)}")

    def get_output_path(self, timestamp: str = None) -> pathlib.Path:
        """出力ファイルパスの生成"""
        if timestamp is None:
            timestamp = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
        return self.output_dir / f"transcription_summary_{timestamp}.txt"

    def is_problematic_transcription(self, text):
        """
        指定されたテキストが問題のあるパターンを含むかどうかを判断します

        Args:
            text (str): チェックする文字起こしテキスト

        Returns:
            bool: 問題がある場合はTrue、それ以外はFalse
        """
        logger.info(f"繰り返しパターンのチェックを実行: テキスト長={len(text)}")
        if not text:
            return False

        # "Take minutes of the meeting"を含むかチェック
        if "Take minutes of the meeting" in text:
            logger.warning("問題パターン検出: 'Take minutes of the meeting'")
            return True

        # まず "utterance" フィールドを抽出して個別にチェック
        try:
            # 修正された正規表現パターン - より柔軟に「utterance」フィールドを抽出
            utterance_patterns = re.findall(r'"utterance"\s*:\s*"((?:[^"\\]|\\.)*)(?:"|$)', text)

            # 抽出の結果をデバッグログに出力
            if utterance_patterns:
                logger.info(f"{len(utterance_patterns)}個の発言を抽出してチェックします")
                logger.debug(f"抽出された発言の先頭50文字: {[u[:50] + '...' for u in utterance_patterns]}")
            else:
                logger.warning(f"発言パターンが抽出できませんでした。テキストサンプル: {text[:200]}...")

            # 発言チェック処理（変更なし）
            for utterance in utterance_patterns:
                if self._check_single_utterance_repetition(utterance):
                    return True
        except Exception as e:
            # 正規表現抽出でエラーが発生した場合はログに記録
            logger.warning(f"発言抽出中にエラーが発生しました: {str(e)}")

        # 個別発言のチェックで問題が見つからなかった場合は全体チェックも実施
        return self._check_whole_text_repetition(text)

    def _check_single_utterance_repetition(self, utterance):
        """
        単一のutterance内での繰り返しをチェック

        Args:
            utterance (str): チェックする発言テキスト

        Returns:
            bool: 問題がある場合はTrue、それ以外はFalse
        """
        logger.debug(f"発言内の繰り返しをチェック: {utterance[:50]}...")

        # 単語チェック
        words = utterance.split()
        for word in words:
            if len(word) <= 1:  # 1文字の単語はスキップ
                continue
            count = words.count(word)
            if count >= 80:
                logger.warning(f"問題パターン検出: 発言内で単語 '{word}' が {count} 回繰り返されています")
                return True

        # フレーズチェック（短いフレーズの繰り返し）
        problem_phrases = ["うん。", "はい。", "ええ。", "あの。", "えー。"]
        for phrase in problem_phrases:
            count = utterance.count(phrase)
            if count >= 70:
                logger.warning(f"問題パターン検出: 発言内でフレーズ '{phrase}' が {count} 回繰り返されています")
                return True

        return False

    def _check_whole_text_repetition(self, text):
        """
        テキスト全体での繰り返しをチェック
        """
        logger.debug(f"テキスト全体の繰り返しをチェック: {text[:200]}...")

        # フォールバックチェック: 繰り返しフレーズを直接検索
        problem_phrases = ["うん。", "はい。", "ええ。", "あの。", "えー。"]
        for phrase in problem_phrases:
            # 長さ3以上のフレーズだけチェック（短すぎるとヒット率が高くなりすぎる）
            if len(phrase) >= 2:
                consecutive_pattern = phrase * 70  # 70回連続の繰り返しパターン
                if consecutive_pattern in text:
                    logger.warning(f"問題パターン検出: フレーズ '{phrase}' が大量に連続して出現しています")
                    return True

                # 出現回数も数える
                count = text.count(phrase)
                if count >= 200:
                    logger.warning(f"問題パターン検出: フレーズ '{phrase}' が全体で {count} 回出現しています")
                    return True

        return False