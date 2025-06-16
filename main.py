import os
import logging
from fortran_analyzer import FortranAnalyzer
from mermaid_generator import MermaidGenerator
from japanese_encoding import detect_encoding_and_read_file # 文字コード判別用
import json


# ログ設定
def setup_logging():
    """
    ログ設定を構成し、ファイルとコンソールの両方に出力します。
    ログファイル 'fortran_analyzer.log' は実行ごとに新しく作成されます。
    """
    log_filename = 'fortran_analyzer.log'
    # 既存のログファイルをクリア
    with open(log_filename, 'w', encoding='utf-8') as f:
        pass
    logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s',
                        filename=log_filename, filemode='a', encoding='utf-8')
    console = logging.StreamHandler()
    console.setLevel(logging.INFO)
    formatter = logging.Formatter('%(levelname)s: %(message)s')
    console.setFormatter(formatter)
    logging.getLogger('').addHandler(console)

# メイン処理
def main():
    setup_logging()
    
    # 解析対象のFortranファイルパス
    # Windowsパスの指定には r"..." (raw文字列) を使うか、スラッシュを順方向にする
    #fortran_file_path = r"C:\00miyatake\99Python\_Python_fparser2\j2d_tnshoku_ver5.f90"
    fortran_file_path = r"E:\21_DATA\02Python\01fortran_analyze\20250615\j2d_tnshoku_ver5.f90"
    # 出力ディレクトリ
    output_directory = "mermaid_charts"
    
    # 各種出力ファイルのパスを定義
    analysis_data_output_path = os.path.join(output_directory, "flow_data.json")
    text_report_output_path = "flow_report.txt"  # カレントディレクトリに出力
    
    # 出力ディレクトリが存在しない場合は作成
    if not os.path.exists(output_directory):
        os.makedirs(output_directory)
        logging.info(f"出力ディレクトリを作成しました: {output_directory}")

    # ファイルの存在チェック
    if not os.path.exists(fortran_file_path):
        logging.error(f"入力ファイルが見つかりません: {fortran_file_path}")
        print(f"エラー: 入力ファイル '{fortran_file_path}' が見つかりません。パスを確認してください。")
        return

    logging.info(f"Fortranソースコード解析を開始します: {fortran_file_path}")
    analyzer = FortranAnalyzer()
    
    # ファイルの読み込みは Analyzer の外で行う
    lines, encoding = detect_encoding_and_read_file(fortran_file_path)
    if lines is None:
        logging.error(f"ファイルの読み込みに失敗しました: {fortran_file_path}")
        print(f"エラー: ファイル '{fortran_file_path}' の読み込みに失敗しました。")
        return

    analysis_result = analyzer.analyze(lines)

    if analysis_result:
        logging.info("--- 解析結果サマリー ---")
        print("\n" + "="*50 + "\n Fortran Code Analyzer - Summary\n" + "="*50)
        
        # 解析状況ファイルを生成
        analyzer.export_analysis_data(analysis_data_output_path)
        print(f"解析状況の詳細は '{analysis_data_output_path}' に保存されました。")

        # ネストレベル付きテキストレポートを生成 **ここを追加**
        analyzer.generate_nested_text_report(text_report_output_path)
        print(f"ネストレベル付きテキストレポートは '{text_report_output_path}' に保存されました。")


        for unit_name, data in [(u['name'], u) for u in analysis_result['units']]:
            calls = [a['target'] for a in data['structures'] if a['type'] == 'CALL']
            includes = [a['target'] for a in data['structures'] if a['type'] == 'INCLUDE']
            summary = (f"  - {unit_name:<20} | "
                       f"Type: {data.get('type', 'N/A'):<10} | "
                       f"CALLs: {len(calls):<2} | "
                       f"INCLUDEs: {len(includes):<2} | "
                       f"Lines: {data['start_line']}-{data['end_line']}")
            print(summary)
            logging.info(summary)
        
        # Mermaidチャートを生成
        logging.info(f"Mermaidフローチャートの生成を開始します。出力先: {output_directory}")
        mermaid_gen = MermaidGenerator(analysis_result, output_directory)
        # generate_flowcharts メソッドには Fortran ファイルのパスではなく、
        # 解析結果全体を渡すか、あるいは内部でファイル名を解決するロジックが必要です。
        # ここでは解析結果を渡すのが自然なので、mermaid_generator.py の generate_flowcharts を調整する必要があるかもしれません。
        # 一旦、既存の引数を維持します。
        mermaid_gen.generate_flowcharts(fortran_file_path) 

        print(f"\n解析ログは 'fortran_analyzer.log' に、")
        print(f"Mermaidチャートは '{output_directory}' フォルダに保存されました。")
    else:
        logging.error("解析に失敗しました。詳細についてはログファイルを確認してください。")
        print("エラー: ソースコードの解析に失敗しました。ログファイルで詳細を確認してください。")

if __name__ == "__main__":
    main()