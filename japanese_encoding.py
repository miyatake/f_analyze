import chardet
from charset_normalizer import from_path

def detect_encoding_and_read_file(file_path, sample_size=2048):
    """
    ファイルのエンコーディングを検出し、ファイルの内容を読み込みます。
    Chardet, charset-normalizerを併用し、Shift-JISの誤判定を補正し、CP932にフォールバックします。
    Returns: tuple (list of lines, detected encoding string) or (None, None) on error.
    """
    try:
        with open(file_path, 'rb') as f:
            raw_data_sample = f.read(sample_size)
            f.seek(0)
        
        # 1. chardetで初期判別
        chardet_result = chardet.detect(raw_data_sample)
        initial_chardet_encoding = chardet_result['encoding']
        initial_chardet_confidence = chardet_result['confidence']
        
        print(f"chardet 初期検出: {initial_chardet_encoding} (信頼度: {initial_chardet_confidence:.2f})")

        # 最終的な検出エンコーディングの現在のベスト候補
        current_best_encoding = initial_chardet_encoding

        # 2. chardetが誤判定しやすいWindows-1252/ISO-8859-1をCP932に補正
        if current_best_encoding in ["Windows-1252", "ISO-8859-1"]:
            current_best_encoding = "cp932"
            print(f"エンコーディング補正 (chardet誤判定): {current_best_encoding}")

        # 3. より精度の高い charset-normalizer で補助的に確認
        if current_best_encoding is None or \
           current_best_encoding.lower() in ["ascii", "unknown"] or \
           initial_chardet_confidence < 0.9:
            
            try:
                cn_result = from_path(file_path).best() 
                if cn_result and cn_result.encoding:
                    if cn_result.encoding.lower() in ["shift_jis", "cp932"]:
                        cn_detected_encoding = "cp932"
                    else:
                        cn_detected_encoding = cn_result.encoding

                    if current_best_encoding not in ["cp932"]:
                        current_best_encoding = cn_detected_encoding
                        print(f"charset-normalizerによる検出: {current_best_encoding}")
                else:
                    print("charset-normalizerでも明確なエンコーディングを検出できませんでした。")
            except Exception as cn_e:
                print(f"charset-normalizerの実行中にエラーが発生しました: {cn_e}")

        # 4. 最終的なCP932へのフォールバック (Windows環境向け)
        final_detected_encoding = current_best_encoding

        if initial_chardet_confidence < 0.9 or \
           final_detected_encoding is None or final_detected_encoding.lower() in ["ascii", "unknown"]:
            
            if final_detected_encoding not in ["cp932"] and \
               final_detected_encoding not in ["utf-8", "utf-8-sig"]:
                print(f"最終フォールバック: 検出信頼度({initial_chardet_confidence:.2f})が低く、検出結果が非CP932系/非UTF-8のためCP932を使用。")
                final_detected_encoding = "cp932"
            elif final_detected_encoding in ["utf-8", "utf-8-sig"] and initial_chardet_confidence < 0.9:
                print(f"最終フォールバック: UTF-8検出だが信頼度({initial_chardet_confidence:.2f})低のためCP932を使用。")
                final_detected_encoding = "cp932"
            elif final_detected_encoding is None or final_detected_encoding.lower() in ["ascii", "unknown"]:
                print("最終フォールバック: エンコーディング不明またはASCIIのみのためCP932を使用。")
                final_detected_encoding = "cp932"
        
        # 確定したエンコーディングでファイルを読み込む
        with open(file_path, 'r', encoding=final_detected_encoding, errors='ignore') as f:
            lines = f.readlines()
        return lines, final_detected_encoding
    except Exception as e:
        print(f"ファイルの読み込みまたは文字コード判別中にエラーが発生しました: {e}")
        return None, None

def main():
    # テスト用のファイルパス
    file_path = "j2d_tnshoku_ver5.f90"
    
    # エンコーディング検出とファイル読み込み
    lines, encoding = detect_encoding_and_read_file(file_path)
    
    if lines is not None and encoding is not None:
        print(f"\n=== エンコーディング情報 ===")
        print(f"検出されたエンコーディング: {encoding}")
        print(f"読み込んだ行数: {len(lines)}")
    else:
        print("ファイルの読み込みに失敗しました")

if __name__ == "__main__":
    main()