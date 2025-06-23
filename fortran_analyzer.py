import re
import os
import collections
import json
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

class FortranAnalyzer:
    def __init__(self):
        # 正規表現パターンを初期化
        self.re_patterns = {
            'program_unit_decl': re.compile(r"^\s*(PROGRAM|SUBROUTINE|FUNCTION|MODULE)\s+([a-zA-Z0-9_]+)", re.IGNORECASE),
            'call': re.compile(r"\bCALL\s+([a-zA-Z0-9_]+(?:\s*\(.*?\))?)", re.IGNORECASE), 
            'include': re.compile(r"^\s*INCLUDE\s*['\"](.+?)['\"]", re.IGNORECASE),
            'fixed_form_label': re.compile(r"^\s*(\d{1,5})\s*[^0-9\s]", re.IGNORECASE), 
            'block_if': re.compile(r"^\s*IF\s*\(.+\)\s*THEN", re.IGNORECASE),
            'logical_if': re.compile(r"^\s*IF\s*\((.+?)\)\s*(?!THEN)(.+)", re.IGNORECASE), 
            'else_if': re.compile(r"^\s*ELSE\s*IF\s*\(.+\)\s*THEN", re.IGNORECASE),
            'else': re.compile(r"^\s*ELSE\b", re.IGNORECASE),
            'end_if': re.compile(r"^\s*END\s*IF", re.IGNORECASE),
            'do': re.compile(r"^\s*DO(\s+\d+)?\s+.*", re.IGNORECASE), # ラベル付き/なしDOを検出
            'end_do': re.compile(r"^\s*END\s*DO", re.IGNORECASE), # END DOを検出
            'select_case': re.compile(r"^\s*SELECT\s+CASE\s*\(.+\)", re.IGNORECASE),
            'case': re.compile(r"^\s*CASE(?:\s*\(.+\))?", re.IGNORECASE), 
            'end_select': re.compile(r"^\s*END\s+SELECT", re.IGNORECASE),
            'goto': re.compile(r"^\s*GOTO\s+(\d+)", re.IGNORECASE),
            'return': re.compile(r"^\s*RETURN", re.IGNORECASE),
            'stop': re.compile(r"^\s*STOP", re.IGNORECASE),
            'continue_stmt': re.compile(r"^\s*CONTINUE", re.IGNORECASE), # 単独のCONTINUE文を検出
            'comment_fixed_form': re.compile(r'^[C*!]', re.IGNORECASE), 
            'inline_comment': re.compile(r'!(.*)'), 
            # プログラムユニットの終了を示すEND文のみを厳密に識別するため、パターンを調整
            # 例: 'END SUBROUTINE', 'END PROGRAM'
            'strict_end_unit': re.compile(r"^\s*END\s*(PROGRAM|SUBROUTINE|FUNCTION|MODULE)\b", re.IGNORECASE),
            # 単独のEND文。ただし、END DO, END IF, END SELECT ではないもの
            'generic_end_standalone': re.compile(r"^\s*END\b(?!\s*(?:DO|IF|SELECT))", re.IGNORECASE),
        }
        self.analysis_result = collections.OrderedDict()

    def analyze(self, lines):
        """
        Fortranファイルの行リストを解析し、構造化されたデータを生成します。
        """
        # 1. プログラムユニットの特定（PROGRAM, SUBROUTINE, FUNCTION, MODULE）
        units = self._identify_program_units(lines)

        # 2. 各ユニット内の詳細なアクションと制御構造の解析
        self._analyze_unit_contents(units, lines)

        # 3. ネストレベルの計算と結果への追加
        for unit in units:
            unit['structures'] = self._calculate_nesting(unit['structures'])

        self.analysis_result['units'] = units
        return self.analysis_result

    def _identify_program_units(self, lines):
        """
        Fortranソースコード内のプログラムユニット（PROGRAM, SUBROUTINE, FUNCTION, MODULE）を特定します。
        PROGRAM宣言がない場合の「暗黙のメインプログラム」も考慮します。
        """
        units = []
        current_unit = None
        has_explicit_program = False

        for i, raw_line in enumerate(lines):
            line_num = i + 1
            if self.re_patterns['comment_fixed_form'].match(raw_line):
                continue
            
            code_part = self.re_patterns['inline_comment'].sub('', raw_line).strip()
            if not code_part:
                continue

            match = self.re_patterns['program_unit_decl'].match(code_part)
            if match:
                # 既存のユニットがあれば、その終了行を確定
                if current_unit:
                    current_unit['end_line'] = line_num - 1 # 新しいユニットの前の行
                
                unit_type, unit_name = match.groups()
                new_unit = {
                    'name': unit_name.upper(),
                    'type': unit_type.upper(),
                    'start_line': line_num,
                    'end_line': len(lines), # 仮の終了行 (ファイル末尾)
                    'structures': []
                }
                units.append(new_unit)
                current_unit = new_unit
                if unit_type.upper() == 'PROGRAM':
                    has_explicit_program = True
            
            # ユニットの厳密な終了文を検出 (例: END SUBROUTINE)
            elif self.re_patterns['strict_end_unit'].match(code_part):
                if current_unit:
                    current_unit['end_line'] = line_num
                    current_unit = None
            # 単独のEND文も考慮（これがユニットの終わりである可能性）。ただし、DO/IF/SELECTブロックの終了ではないことを確認
            elif self.re_patterns['generic_end_standalone'].match(code_part):
                if current_unit:
                    current_unit['end_line'] = line_num
                    current_unit = None


        # 最後のユニットの終了行を調整 (ファイル末尾まで続く場合)
        # もし最後のユニットが明確なEND文で終わっていない場合、ファイルの最後までとする
        if current_unit:
            # current_unit がまだNoneでない場合、それはファイルの最後に到達したことを意味する
            # または、END文がなかった場合
            if current_unit['end_line'] == len(lines): # まだ仮の終了行の場合
                current_unit['end_line'] = len(lines)


        # PROGRAM宣言がない場合の「暗黙のメインプログラム」処理
        # ファイルの開始から最初のユニットまでの部分を「PROGRAM_NONAME」として扱う
        if not has_explicit_program:
            # 最初のユニットが始まる行、またはファイル全体の行数
            first_unit_start_line = units[0]['start_line'] if units else len(lines) + 1
            
            if first_unit_start_line > 1: # ファイルの最初の行から始まっていない場合
                noname_program = {
                    'name': 'PROGRAM_NONAME',
                    'type': 'PROGRAM',
                    'start_line': 1,
                    'end_line': first_unit_start_line - 1,
                    'structures': []
                }
                units.insert(0, noname_program)
        elif not units and lines: # ファイル全体にユニット宣言がない場合
            # ファイル全体が単一の無名プログラムと見なされる
            noname_program = {
                'name': 'PROGRAM_NONAME',
                'type': 'PROGRAM',
                'start_line': 1,
                'end_line': len(lines),
                'structures': []
            }
            units.append(noname_program)

        return units

    def _analyze_unit_contents(self, units, lines):
        """
        各プログラムユニットの内部を解析し、主要なステートメントを抽出・構造化します。
        各行に対して、最も適切な単一の構造を特定します。
        """
        for unit in units:
            unit_end_idx = min(unit['end_line'], len(lines))
            unit_lines_raw = lines[unit['start_line'] - 1 : unit_end_idx]
            
            for i, raw_line in enumerate(unit_lines_raw):
                line_num = unit['start_line'] + i
                
                # コメントを除去し、空白をトリムしたコード部分
                line_content_no_comment = self.re_patterns['inline_comment'].sub('', raw_line)
                code_part_stripped = line_content_no_comment.strip()
                
                if not code_part_stripped: # 空行またはコメントのみの行はスキップ
                    continue

                # まずラベルを抽出 (もし存在すれば)
                current_label = None
                label_match_at_start = self.re_patterns['fixed_form_label'].match(raw_line)
                if label_match_at_start:
                    current_label = label_match_at_start.group(1).strip()
                    # ラベル部分をコードから除去して、ステートメントの識別に使う
                    code_part_stripped = re.sub(r"^\s*\d{1,5}", "", line_content_no_comment).strip()
                
                # 行の最も具体的なタイプを決定
                statement_type = 'OTHER_STATEMENT' # デフォルト
                extra_args = {}

                # 優先順位付けされたパース (より具体的なFortran構文から順にチェック)
                
                # 1. ブロック終了ステートメント (END DO, END IF, END SELECT, およびラベル付きCONTINUE)
                if self.re_patterns['end_do'].match(code_part_stripped):
                    statement_type = 'END_DO'
                elif self.re_patterns['end_if'].match(code_part_stripped):
                    statement_type = 'END_IF'
                elif self.re_patterns['end_select'].match(code_part_stripped):
                    statement_type = 'END_SELECT'
                # ラベル付きCONTINUE (END DOとして機能することが多い)
                elif self.re_patterns['continue_stmt'].match(code_part_stripped) and current_label:
                    statement_type = 'CONTINUE_END_DO'
                    extra_args['label'] = current_label # ラベルを保持
                
                # 2. ユニット終了ステートメント (END PROGRAM/SUBROUTINE/FUNCTION/MODULE, および単独のEND)
                # これらの行は_identify_program_unitsでも境界として識別されるが、構造としても追加
                elif self.re_patterns['strict_end_unit'].match(code_part_stripped):
                    statement_type = 'END_UNIT_STRICT'
                elif self.re_patterns['generic_end_standalone'].match(code_part_stripped):
                    statement_type = 'END'

                # 3. ブロック開始ステートメント (DO, IF THEN, SELECT CASE)
                elif self.re_patterns['do'].match(code_part_stripped):
                    statement_type = 'DO_BLOCK_START'
                elif self.re_patterns['block_if'].match(code_part_stripped):
                    statement_type = 'IF_BLOCK_START'
                    match = re.match(r'^\s*IF\s*\((.+)\)\s*THEN', code_part_stripped, re.IGNORECASE)
                    if match: # 必ずマッチするはずだが、念のため
                        extra_args['condition'] = match.group(1).strip()
                elif self.re_patterns['select_case'].match(code_part_stripped):
                    statement_type = 'SELECT_CASE_START'
                    match = re.match(r'^\s*SELECT\s+CASE\s*\((.+)\)', code_part_stripped, re.IGNORECASE)
                    if match:
                        extra_args['expression'] = match.group(1).strip()
                
                # 4. 条件分岐/制御フロー関連ステートメント (ELSE IF, ELSE, CASE, GOTO, LOGICAL IF)
                elif self.re_patterns['else_if'].match(code_part_stripped):
                    statement_type = 'ELSE_IF'
                    match = re.match(r'^\s*ELSE\s+IF\s*\((.+)\)\s*THEN', code_part_stripped, re.IGNORECASE)
                    if match:
                        extra_args['condition'] = match.group(1).strip()
                elif self.re_patterns['else'].match(code_part_stripped):
                    statement_type = 'ELSE'
                elif self.re_patterns['case'].match(code_part_stripped):
                    statement_type = 'CASE'
                    match = re.match(r'^\s*CASE(?:\s*\((.+)\))?', code_part_stripped, re.IGNORECASE)
                    extra_args['value'] = match.group(1).strip() if match.group(1) else 'DEFAULT'
                elif self.re_patterns['goto'].match(code_part_stripped):
                    statement_type = 'GOTO'
                    match = self.re_patterns['goto'].match(code_part_stripped)
                    if match:
                        extra_args['target_label'] = match.group(1).strip()
                elif self.re_patterns['logical_if'].match(code_part_stripped):
                    statement_type = 'LOGICAL_IF'
                    match = self.re_patterns['logical_if'].match(code_part_stripped)
                    if match:
                        extra_args['condition'] = match.group(1).strip()
                        extra_args['statement'] = match.group(2).strip()

                # 5. CALL および INCLUDE (ネストレベルは変えないが重要な構造要素)
                elif self.re_patterns['call'].match(code_part_stripped):
                    statement_type = 'CALL'
                    # CALLのターゲット名は、引数を含まない関数名のみを抽出
                    call_target_match = re.match(r"\bCALL\s+([a-zA-Z0-9_]+)", code_part_stripped, re.IGNORECASE)
                    extra_args['target'] = call_target_match.group(1).strip().upper() if call_target_match else "UNKNOWN"
                elif self.re_patterns['include'].match(code_part_stripped):
                    statement_type = 'INCLUDE'
                    match = self.re_patterns['include'].match(code_part_stripped)
                    if match:
                        extra_args['target'] = match.group(1).strip("'\"")

                # 6. RETURN, STOP (単独の制御フロー)
                elif self.re_patterns['return'].match(code_part_stripped):
                    statement_type = 'RETURN'
                elif self.re_patterns['stop'].match(code_part_stripped):
                    statement_type = 'STOP'

                # 7. ラベルのみの行、または他のどのタイプにもマッチしなかったラベル付き行
                elif current_label:
                    statement_type = 'LABEL'
                    extra_args['label'] = current_label
                
                # 構造をリストに追加
                unit['structures'].append({
                    'type': statement_type,
                    'line': line_num,
                    'content': raw_line.strip(), # 元の行の完全な内容を保持
                    **extra_args # 条件、ターゲット、ラベルなどの追加引数
                })
            
            unit['structures'].sort(key=lambda x: x['line']) # 行番号でソート


    def _calculate_nesting(self, structures):
        """
        Fortranの制御構造に基づいて、各構造のネストレベルを計算します。
        """
        nested_structures = []
        if_stack = []          # 現在開いているIFブロックの開始行を格納
        do_stack = []          # 現在開いているDOループの開始行とターゲットラベルを格納
        select_case_stack = [] # 現在開いているSELECT CASEの開始行を格納

        for struct in structures:
            # デフォルトのネストレベルは現在のスタックの深さ
            # ELSE/ELSE_IF/END_IF/END_DO/END_SELECT は、デクリメント前に現在のレベルで表示するため、
            # ポップ操作の前にネストレベルを設定する必要がある
            current_nest_level = len(if_stack) + len(do_stack) + len(select_case_stack)
            struct_with_nest = struct.copy() # オリジナルを変更しないためにコピー

            # スタック操作によるネストレベルの調整
            if struct['type'] == 'IF_BLOCK_START':
                if_stack.append(struct['line'])
            elif struct['type'] == 'ELSE_IF' or struct['type'] == 'ELSE':
                # ELSE IF / ELSE は、IFブロックのレベルから1つ下げるように見えるため、
                # ポップするのではなく、表示上のネストレベルを調整
                if if_stack:
                    # 親IFのレベルに合わせるために、現在のif_stackの深さから1を引く
                    # これは表示上の調整であり、論理的なスタックの深さは変わらない
                    current_nest_level = len(if_stack) -1 + len(do_stack) + len(select_case_stack)
                else: # IFブロックが閉じられていない異常ケースだが、念のため
                    current_nest_level = len(do_stack) + len(select_case_stack)
            elif struct['type'] == 'END_IF':
                if if_stack:
                    if_stack.pop()
                    # ポップ後のレベル
                    current_nest_level = len(if_stack) + len(do_stack) + len(select_case_stack)
                else:
                    current_nest_level = 0 # スタックが空の場合は0
            elif struct['type'] == 'DO_BLOCK_START': # DOループ開始
                # ラベル付きDOの場合、ラベルをターゲットとしてスタックに格納
                # 例: DO 10 K=1,KJS
                do_label_match = re.match(r'^\s*DO\s*(\d+)', struct['content'], re.IGNORECASE)
                target_label = do_label_match.group(1).strip() if do_label_match else None
                do_stack.append({'line': struct['line'], 'target_label': target_label})
            elif struct['type'] == 'END_DO' or struct['type'] == 'CONTINUE_END_DO': # END DO または CONTINUE_END_DO
                if do_stack:
                    found_matching_do = False
                    if struct['type'] == 'CONTINUE_END_DO' and struct.get('label'): # ラベル付きCONTINUEの場合
                        # スタックを逆順に見て、対応するラベルのDOを探してポップ
                        for k in range(len(do_stack) - 1, -1, -1):
                            if do_stack[k].get('target_label') == struct['label']:
                                do_stack.pop(k)
                                found_matching_do = True
                                break
                        if not found_matching_do:
                            logging.warning(f"行 {struct['line']}: ラベル {struct['label']} のDOループ終了 (CONTINUE) に対応する開始が見つかりません。")
                    else: # ラベルなしEND DO、またはラベル付きだが対応するDOがないCONTINUE
                        # 直近のDOをポップ
                        do_stack.pop() 
                    current_nest_level = len(if_stack) + len(do_stack) + len(select_case_stack) # ポップ後のレベル
                else:
                    current_nest_level = 0
            elif struct['type'] == 'SELECT_CASE_START':
                select_case_stack.append(struct['line'])
            elif struct['type'] == 'CASE': 
                # CASE文はSELECT CASEブロックの内部だが、ネストレベルを増やすのではなく、
                # 親のSELECT CASEのレベルより1つ深いレベルに設定
                if select_case_stack:
                    current_nest_level = len(if_stack) + len(do_stack) + len(select_case_stack) 
                else:
                    current_nest_level = 0
            elif struct['type'] == 'END_SELECT':
                if select_case_stack:
                    select_case_stack.pop()
                    current_nest_level = len(if_stack) + len(do_stack) + len(select_case_stack)
                else:
                    current_nest_level = 0
            
            # 論理IFやその他のステートメントはスタック操作をしないため、現在のネストレベルをそのまま使用

            # 最終的なネストレベルを構造に追加
            struct_with_nest['nest_level'] = current_nest_level
            nested_structures.append(struct_with_nest)
        return nested_structures

    def export_analysis_data(self, output_filepath='flow_data.json'):
        """
        解析結果データをJSONファイルとして人間が読める形式で出力します。
        各ユニットの制御構造とそのネストレベルを表現します。
        """
        output_dir = os.path.dirname(output_filepath)
        if output_dir and not os.path.exists(output_dir):
            os.makedirs(output_dir)

        serializable_data = self.analysis_result.copy()
        
        try:
            with open(output_filepath, 'w', encoding='utf-8') as f:
                json.dump(serializable_data, f, indent=2, ensure_ascii=False)
            logging.info(f"解析状況ファイルを生成しました: {output_filepath}")
        except Exception as e:
            logging.error(f"解析状況ファイルの保存中にエラーが発生しました: {e}")

    def generate_nested_text_report(self, output_filepath='flow_report.txt', indent_size=4):
        """
        解析結果から、ネストレベルを考慮した人間が読みやすいテキストレポートを生成します。
        """
        output_dir = os.path.dirname(output_filepath)
        if output_dir and not os.path.exists(output_dir):
            os.makedirs(output_dir)

        try:
            with open(output_filepath, 'w', encoding='utf-8') as f:
                if 'units' not in self.analysis_result:
                    f.write("解析データにプログラムユニット情報がありません。\n")
                    return

                for unit in self.analysis_result['units']:
                    f.write(f"=== {unit['type']}: {unit['name']} (Lines: {unit['start_line']}-{unit['end_line']}) ===\n")
                    for struct in unit['structures']:
                        # ネストレベルに応じたインデントを生成
                        indent = " " * (struct.get('nest_level', 0) * indent_size)
                        
                        line_info = f"L{struct['line']}:"
                        content_info = ""

                        # 構造のタイプに応じた表示内容
                        if struct['type'] == 'PROGRAM':
                            content_info = f"PROGRAM {unit['name']}"
                        elif struct['type'] == 'SUBROUTINE_DECL':
                            content_info = f"SUBROUTINE {unit['name']}"
                        elif struct['type'] == 'FUNCTION_DECL':
                            content_info = f"FUNCTION {unit['name']}"
                        elif struct['type'] == 'CALL':
                            content_info = struct['content'].strip() # ここを修正: 引数を含む元の内容を使用
                        elif struct['type'] == 'INCLUDE':
                            content_info = f"INCLUDE '{struct['target']}'"
                        elif struct['type'] == 'IF_BLOCK_START':
                            content_info = f"IF ({struct['condition']}) THEN"
                        elif struct['type'] == 'LOGICAL_IF':
                            content_info = f"IF ({struct['condition']}) {struct['statement']}"
                        elif struct['type'] == 'ELSE_IF':
                            content_info = f"ELSE IF ({struct['condition']}) THEN"
                        elif struct['type'] == 'ELSE':
                            content_info = "ELSE"
                        elif struct['type'] == 'END_IF':
                            content_info = "END IF"
                        elif struct['type'] == 'DO_BLOCK_START':
                            content_info = f"DO {struct['content'].strip().replace('DO ', '')} (Loop: Start)" # 重複DOを削除
                        elif struct['type'] == 'END_DO':
                            content_info = f"END DO (Loop: End)"
                        elif struct['type'] == 'CONTINUE_END_DO':
                             content_info = f"LABEL {struct['label']}: {struct['content'].strip()} (Loop: End)" # ラベルとコンテンツと終了表示
                        elif struct['type'] == 'SELECT_CASE_START':
                            content_info = f"SELECT CASE ({struct['expression']})"
                        elif struct['type'] == 'CASE':
                            content_info = f"CASE ({struct['value']})"
                        elif struct['type'] == 'END_SELECT':
                            content_info = "END SELECT"
                        elif struct['type'] == 'GOTO':
                            content_info = f"GOTO {struct['target_label']}"
                        elif struct['type'] == 'RETURN':
                            content_info = "RETURN"
                        elif struct['type'] == 'STOP':
                            content_info = "STOP"
                        elif struct['type'] == 'LABEL':
                            content_info = f"LABEL {struct['label']}: {struct['content'].strip()}"
                        elif struct['type'] == 'END_UNIT_STRICT': # 厳密なユニットEND
                            content_info = f"END {unit['type']} (Strict)"
                        elif struct['type'] == 'END': # 汎用的なEND
                            content_info = "END"
                        elif struct['type'] == 'OTHER_STATEMENT':
                            content_info = struct['content'].strip()
                        
                        f.write(f"{indent}{line_info:<8} {content_info}\n")
                    f.write("\n") # ユニット間の区切り

            logging.info(f"ネストレベル付きテキストレポートを生成しました: {output_filepath}")
        except Exception as e:
            logging.error(f"テキストレポートの保存中にエラーが発生しました: {e}")
