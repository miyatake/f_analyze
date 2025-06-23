import re
import os
import collections
import json
import logging

# ログ設定はmain.pyで行うため、ここでは省略

class FortranAnalyzer:
    def __init__(self):
        # 正規表現パターンを初期化
        self.re_patterns = {
            'program_unit_decl': re.compile(r"^\s*(PROGRAM|SUBROUTINE|FUNCTION|MODULE)\s+([a-zA-Z0-9_]+)", re.IGNORECASE),
            'call': re.compile(r"\bCALL\s+([a-zA-Z0-9_]+(?:(?:\s*\(.*?\))|\b))", re.IGNORECASE),
            'include': re.compile(r"^\s*INCLUDE\s*['\"](.+?)['\"]", re.IGNORECASE),
            'fixed_form_label': re.compile(r"^\s*(\d{1,5})\s*[^0-9\s]?", re.IGNORECASE), # ラベル後の文字はオプションに
            'block_if': re.compile(r"^\s*IF\s*\((.+)\)\s*THEN", re.IGNORECASE),
            'logical_if': re.compile(r"^\s*IF\s*\((.+?)\)\s*(?!THEN)(.+)", re.IGNORECASE),
            'else_if': re.compile(r"^\s*ELSE\s*IF\s*\((.+)\)\s*THEN", re.IGNORECASE),
            'else': re.compile(r"^\s*ELSE\b", re.IGNORECASE),
            'end_if': re.compile(r"^\s*END\s*IF", re.IGNORECASE),
            'do': re.compile(r"^\s*DO(?:\s*(\d+))?\s*.*", re.IGNORECASE), # ラベル付きDOも含む
            'end_do': re.compile(r"^\s*END\s*DO", re.IGNORECASE),
            'select_case': re.compile(r"^\s*SELECT\s+CASE\s*\((.+)\)", re.IGNORECASE),
            'case': re.compile(r"^\s*CASE(?:\s*\((.+)\))?", re.IGNORECASE),
            'end_select': re.compile(r"^\s*END\s+SELECT", re.IGNORECASE),
            'goto': re.compile(r"^\s*GOTO\s+(\d+)", re.IGNORECASE),
            'return': re.compile(r"^\s*RETURN", re.IGNORECASE),
            'stop': re.compile(r"^\s*STOP", re.IGNORECASE),
            'continue_stmt': re.compile(r"^\s*CONTINUE", re.IGNORECASE), # ラベルの有無にかかわらずCONTINUEを検出
            'comment_fixed_form': re.compile(r'^[C*!]', re.IGNORECASE),
            'inline_comment': re.compile(r'!(.*)'),
            'strict_end_unit': re.compile(r"^\s*END\s*(PROGRAM|SUBROUTINE|FUNCTION|MODULE)\b", re.IGNORECASE),
            'generic_end_standalone': re.compile(r"^\s*END\b(?!\s*(?:DO|IF|SELECT))", re.IGNORECASE),
            # 変数宣言や代入文の簡易的なパターン (その他のステートメントをフィルタリングするため)
            'declaration': re.compile(r'^\s*(dimension|integer|character|double\s+precision|real|logical|complex)\b', re.IGNORECASE),
            'assignment': re.compile(r'^\s*[a-zA-Z_]\w*\s*=\s*.+', re.IGNORECASE),
            'io_statement_read': re.compile(r"^\s*READ\s*\(", re.IGNORECASE),
            'io_statement_write': re.compile(r"^\s*WRITE\s*\(", re.IGNORECASE),
            'io_statement_open_close': re.compile(r"^\s*(OPEN|CLOSE)\s*\(", re.IGNORECASE),
        }
        self.analysis_result = collections.OrderedDict()

    def analyze(self, lines):
        """
        Fortranファイルの行リストを解析し、構造化されたデータを生成します。
        Args:
            lines (list): Fortranソースコードの各行を要素とするリスト。
        Returns:
            collections.OrderedDict: 解析結果を格納した辞書。
        """
        logging.info("Fortranソースコードのプログラムユニットを識別中...")
        units = self._identify_program_units(lines)
        logging.info(f"{len(units)}個のプログラムユニットを識別しました。")
        
        logging.info("各プログラムユニットの内容を解析中...")
        self._analyze_unit_contents(units, lines)
        
        logging.info("ネストレベルを計算中...")
        for unit in units:
            unit['structures'] = self._calculate_nesting(unit['structures'])
        
        self.analysis_result['units'] = units
        logging.info("Fortranソースコードの解析が完了しました。")
        return self.analysis_result

    def _identify_program_units(self, lines):
        """
        Fortranソースコード内のプログラムユニット（PROGRAM, SUBROUTINE, FUNCTION, MODULE）を特定します。
        PROGRAM宣言がない場合の「暗黙のメインプログラム」も考慮します。
        Args:
            lines (list): Fortranソースコードの各行。
        Returns:
            list: 各プログラムユニットの情報を格納した辞書のリスト。
        """
        units = []
        current_unit = None
        has_explicit_program = False

        for i, raw_line in enumerate(lines):
            line_num = i + 1
            # 固定形式のコメント行はスキップ
            if self.re_patterns['comment_fixed_form'].match(raw_line):
                continue
            
            # インラインコメントを除去し、実効コード部分を抽出
            code_part = self.re_patterns['inline_comment'].sub('', raw_line).strip()
            if not code_part: # 空行になったらスキップ
                continue

            match = self.re_patterns['program_unit_decl'].match(code_part)
            if match:
                if current_unit:
                    # 前のユニットの終了行を現在のユニットの開始行の直前に設定
                    if current_unit['end_line'] == len(lines): # まだファイルの最後までと設定されている場合
                        current_unit['end_line'] = line_num - 1
                
                unit_type, unit_name = match.groups()
                new_unit = {
                    'name': unit_name.upper(),
                    'type': unit_type.upper(),
                    'start_line': line_num,
                    'end_line': len(lines), # 初期値はファイルの最後まで
                    'structures': []
                }
                units.append(new_unit)
                current_unit = new_unit
                if unit_type.upper() == 'PROGRAM':
                    has_explicit_program = True
            # 厳密なENDユニット（例: END PROGRAM, END SUBROUTINE）
            elif self.re_patterns['strict_end_unit'].match(code_part):
                if current_unit and code_part.upper().endswith(current_unit['type']):
                    current_unit['end_line'] = line_num
                    current_unit = None
                elif current_unit: # strict_end_unitにマッチしたがタイプが一致しない場合（例: PROGRAMユニットでEND SUBROUTINE）
                    logging.warning(f"Line {line_num}: Mismatched END unit '{code_part.strip()}' in '{current_unit['name']}'. Assuming end of unit.")
                    current_unit['end_line'] = line_num
                    current_unit = None
            # 単独のEND文
            elif self.re_patterns['generic_end_standalone'].match(code_part):
                if current_unit:
                    current_unit['end_line'] = line_num
                    current_unit = None

        # ファイルの最後までユニットが閉じられなかった場合の処理
        if current_unit and current_unit['end_line'] == len(lines):
            # 最後のユニットがファイルの最後まで続く場合、そのままで良い
            pass

        # 明示的なPROGRAMがない場合、先頭から最初のユニットまでの範囲を「PROGRAM_NONAME」とする
        if not has_explicit_program:
            # 最初の明示的なユニットの開始行を検索
            first_explicit_unit_start_line = len(lines) + 1
            if units:
                first_explicit_unit_start_line = units[0]['start_line']
            
            if first_explicit_unit_start_line > 1:
                noname_program = {
                    'name': 'PROGRAM_NONAME',
                    'type': 'PROGRAM',
                    'start_line': 1,
                    'end_line': first_explicit_unit_start_line - 1,
                    'structures': []
                }
                units.insert(0, noname_program)
        
        # ユニットが全く見つからなかった場合（ファイル全体が暗黙のPROGRAM）
        elif not units and lines:
            noname_program = {
                'name': 'PROGRAM_NONAME',
                'type': 'PROGRAM',
                'start_line': 1,
                'end_line': len(lines),
                'structures': []
            }
            units.append(noname_program)
        
        # ユニットの重複や不正なend_lineを修正 (念のため)
        # 終了行が次のユニットの開始行より大きい場合や、ユニット同士が重なっている場合
        units_sorted = sorted(units, key=lambda x: x['start_line'])
        cleaned_units = []
        for i, unit in enumerate(units_sorted):
            if i > 0 and unit['start_line'] <= cleaned_units[-1]['end_line']:
                # 前のユニットと重複する場合、前のユニットの終了行を調整
                logging.warning(f"Adjusting end_line for {cleaned_units[-1]['name']} (line {cleaned_units[-1]['end_line']}) due to overlap with {unit['name']} (line {unit['start_line']}).")
                cleaned_units[-1]['end_line'] = unit['start_line'] - 1
            cleaned_units.append(unit)
        
        return cleaned_units

    def _analyze_unit_contents(self, units, lines):
        """
        各プログラムユニットの内部を解析し、主要なステートメントを抽出・構造化します。
        各行に対して、最も適切な単一の構造を特定します。
        Args:
            units (list): プログラムユニットの情報を格納した辞書のリスト。
            lines (list): Fortranソースコードの各行。
        """
        for unit in units:
            # ユニットのコンテンツ範囲を正確に設定
            # Fortran Analyzer の unit['start_line'] は宣言行自体を指すため、
            # content の開始は宣言行の次から、または宣言行自体が content になる場合がある。
            # ここでは宣言行も一緒に解析し、structures に含める。
            unit_start_idx = unit['start_line'] - 1 # リストのインデックスは0から
            unit_end_idx = min(unit['end_line'], len(lines)) # min で安全確保
            
            unit_lines_raw = lines[unit_start_idx : unit_end_idx]
            
            temp_structures_for_unit = []

            # ユニットの宣言自身も構造として追加（ネストレベル0）。
            # ただし、PROGRAM_NONAMEの場合は宣言行が存在しないため、最初の実行可能な行を考慮する。
            if unit['type'] in ['PROGRAM', 'SUBROUTINE', 'FUNCTION', 'MODULE'] and unit['name'] != 'PROGRAM_NONAME':
                unit_decl_content = lines[unit['start_line']-1].strip() if unit['start_line'] <= len(lines) else ""
                temp_structures_for_unit.append({
                    'type': f"{unit['type']}_DECL",
                    'line': unit['start_line'],
                    'content': unit_decl_content,
                    'name': unit['name']
                })

            for i, raw_line in enumerate(unit_lines_raw):
                # 実際の行番号を計算 (unit_lines_raw の i は 0 から始まる相対インデックス)
                line_num = unit_start_idx + i + 1 
                original_line_content = raw_line.rstrip() # 改行文字を除去した元の行

                # 固定形式のコメント行はスキップ
                if self.re_patterns['comment_fixed_form'].match(raw_line):
                    continue
                
                # インラインコメントを除去し、実効コード部分を抽出
                code_effective_part = self.re_patterns['inline_comment'].sub('', raw_line)
                code_effective_part_stripped = code_effective_part.strip()
                
                # 行が空になったらスキップ
                if not code_effective_part_stripped:
                    continue

                current_label = None
                code_after_label_or_original_stripped = code_effective_part_stripped # デフォルト

                # 行頭ラベルの検出 (固定形式Fortran用)
                label_match_on_raw = self.re_patterns['fixed_form_label'].match(raw_line)
                if label_match_on_raw:
                    current_label = label_match_on_raw.group(1).strip()
                    # ラベル以降のコード部分を取得し、そこからさらにコメントを除去
                    code_after_label_or_original_stripped = raw_line[label_match_on_raw.end():].strip()
                    code_after_label_or_original_stripped = self.re_patterns['inline_comment'].sub('', code_after_label_or_original_stripped).strip()
                    
                    # ラベルのみの行の場合の特別な扱い
                    if not code_after_label_or_original_stripped:
                        temp_structures_for_unit.append({
                            'type': 'LABEL',
                            'line': line_num,
                            'content': original_line_content,
                            'label': current_label
                        })
                        continue # この行はラベルとして処理済み

                statement_type = 'OTHER_STATEMENT' # デフォルトのタイプ
                extra_args = {}

                # ラベルが検出された場合、それを常に extra_args に追加
                if current_label:
                    extra_args['label'] = current_label

                # 最も具体的なステートメントタイプから順にチェック
                # CONTINUE は最優先で処理し、それが DO の終了である可能性を考慮
                if self.re_patterns['continue_stmt'].match(code_after_label_or_original_stripped):
                    statement_type = 'CONTINUE_END_DO'
                # 明示的なブロック終了ステートメント
                elif self.re_patterns['end_do'].match(code_after_label_or_original_stripped):
                    statement_type = 'END_DO'
                elif self.re_patterns['end_if'].match(code_after_label_or_original_stripped):
                    statement_type = 'END_IF'
                elif self.re_patterns['end_select'].match(code_after_label_or_original_stripped):
                    statement_type = 'END_SELECT'
                # ユニット終了ステートメント
                elif self.re_patterns['strict_end_unit'].match(code_after_label_or_original_stripped):
                    statement_type = 'END_UNIT_STRICT'
                elif self.re_patterns['generic_end_standalone'].match(code_after_label_or_original_stripped):
                    statement_type = 'END'
                # ブロック開始ステートメント
                elif self.re_patterns['do'].match(code_after_label_or_original_stripped):
                    statement_type = 'DO_BLOCK_START'
                    match = self.re_patterns['do'].match(code_after_label_or_original_stripped)
                    if match and match.group(1): # ラベル付きDOの場合、そのラベルを優先
                        extra_args['label'] = match.group(1).strip()
                elif self.re_patterns['block_if'].match(code_after_label_or_original_stripped):
                    statement_type = 'IF_BLOCK_START'
                    match = self.re_patterns['block_if'].match(code_after_label_or_original_stripped)
                    if match:
                        extra_args['condition'] = match.group(1).strip()
                elif self.re_patterns['select_case'].match(code_after_label_or_original_stripped):
                    statement_type = 'SELECT_CASE_START'
                    match = self.re_patterns['select_case'].match(code_after_label_or_original_stripped)
                    if match:
                        extra_args['expression'] = match.group(1).strip()
                # 条件分岐/制御フロー関連ステートメント
                elif self.re_patterns['else_if'].match(code_after_label_or_original_stripped):
                    statement_type = 'ELSE_IF'
                    match = self.re_patterns['else_if'].match(code_after_label_or_original_stripped)
                    if match:
                        extra_args['condition'] = match.group(1).strip()
                elif self.re_patterns['else'].match(code_after_label_or_original_stripped):
                    statement_type = 'ELSE'
                elif self.re_patterns['case'].match(code_after_label_or_original_stripped):
                    statement_type = 'CASE'
                    match = self.re_patterns['case'].match(code_after_label_or_original_stripped)
                    extra_args['value'] = match.group(1).strip() if match and match.group(1) else 'DEFAULT'
                elif self.re_patterns['goto'].match(code_after_label_or_original_stripped):
                    statement_type = 'GOTO'
                    match = self.re_patterns['goto'].match(code_after_label_or_original_stripped)
                    if match:
                        extra_args['target_label'] = match.group(1).strip()
                elif self.re_patterns['logical_if'].match(code_after_label_or_original_stripped):
                    statement_type = 'LOGICAL_IF'
                    match = self.re_patterns['logical_if'].match(code_after_label_or_original_stripped)
                    if match:
                        extra_args['condition'] = match.group(1).strip()
                        extra_args['statement'] = match.group(2).strip()
                # CALL および INCLUDE
                elif self.re_patterns['call'].match(code_after_label_or_original_stripped):
                    statement_type = 'CALL'
                    call_match = self.re_patterns['call'].match(code_after_label_or_original_stripped)
                    if call_match:
                        target_full = call_match.group(1).strip()
                        extra_args['target'] = target_full.split('(')[0].strip().upper()
                        extra_args['full_call_content'] = target_full
                    else:
                        extra_args['target'] = "UNKNOWN"
                elif self.re_patterns['include'].match(code_after_label_or_original_stripped):
                    statement_type = 'INCLUDE'
                    match = self.re_patterns['include'].match(code_after_label_or_original_stripped)
                    if match:
                        extra_args['target'] = match.group(1).strip("'\"")
                # RETURN, STOP
                elif self.re_patterns['return'].match(code_after_label_or_original_stripped):
                    statement_type = 'RETURN'
                elif self.re_patterns['stop'].match(code_after_label_or_original_stripped):
                    statement_type = 'STOP'
                # その他のステートメント（ラベルのみの行は上で処理済み）
                # OTHER_STATEMENT に分類されるが、特にフロー制御に関わらないものには 'is_noise' フラグを付ける
                # これは flow_report.txt でのフィルタリングに役立つ
                elif statement_type == 'OTHER_STATEMENT':
                    content_lower = code_after_label_or_original_stripped.lower()
                    if (self.re_patterns['declaration'].match(content_lower) or
                        self.re_patterns['assignment'].match(content_lower) or
                        self.re_patterns['io_statement_read'].match(content_lower) or
                        self.re_patterns['io_statement_write'].match(content_lower) or
                        self.re_patterns['io_statement_open_close'].match(content_lower)):
                        extra_args['is_noise'] = True # 後でレポートから除外するため
                    
                temp_structures_for_unit.append({
                    'type': statement_type,
                    'line': line_num,
                    'content': original_line_content,
                    **extra_args
                })

            # 各行の構造を一時的に保持するリスト
            final_unique_structures = []
            
            # 各行番号に対して最も優先される構造を保持するための辞書
            # {line_num: {'priority': int, 'struct': struct_dict}}
            priority_map = {
                'CONTINUE_END_DO': 100,
                'END_DO': 95,
                'END_IF': 95,
                'END_SELECT': 95,
                'END_UNIT_STRICT': 90,
                'END': 90,
                'IF_BLOCK_START': 80,
                'DO_BLOCK_START': 80,
                'SELECT_CASE_START': 80,
                'ELSE_IF': 75, 'ELSE': 75, 'CASE': 75,
                'CALL': 70,
                'GOTO': 65,
                'LOGICAL_IF': 60,
                'RETURN': 55,
                'STOP': 55,
                'LABEL': 50, # GOTOターゲットとして必要
                'INCLUDE': 40, # INCLUDEは制御フローではないが、flow_data.jsonには含める
                'PROGRAM_DECL': 5, 'SUBROUTINE_DECL': 5, 'FUNCTION_DECL': 5, 'MODULE_DECL': 5,
                'OTHER_STATEMENT': 10, # 最も低い優先度
            }

            best_struct_on_line = {} # {line_num: struct_dict}

            for struct in temp_structures_for_unit:
                line = struct['line']
                current_type = struct['type']
                current_priority = priority_map.get(current_type, 0)

                if line not in best_struct_on_line:
                    best_struct_on_line[line] = struct
                else:
                    existing_struct = best_struct_on_line[line]
                    existing_priority = priority_map.get(existing_struct['type'], 0)

                    if current_priority > existing_priority:
                        best_struct_on_line[line] = struct
                    elif current_priority == existing_priority:
                        # 同じ優先度の場合、より詳細な情報を持つ方を優先
                        # 例えば、ラベルを持つOTHER_STATEMENTが単なるLABELより優先されるなど
                        # 現状のpriority_mapと`CONTINUE_END_DO`の優先度設定でこの問題は解決されているはず
                        pass # 既存のものを維持（最初のマッチが優先）

            # 最終結果リストを生成
            for line_num in sorted(best_struct_on_line.keys()):
                final_unique_structures.append(best_struct_on_line[line_num])

            unit['structures'] = sorted(final_unique_structures, key=lambda x: x['line'])


    def _calculate_nesting(self, structures):
        """
        Fortranの制御構造に基づいて、各構造のネストレベルを計算します。
        共有DOラベル（同一ラベルで複数のDOが閉じる）に対応します。
        Args:
            structures (list): 解析されたステートメントのリスト。
        Returns:
            list: ネストレベルが追加されたステートメントのリスト。
        """
        nested_structures = []
        if_stack = []          # IFブロックの開始行番号を格納
        # DOブロックの開始情報を格納: [{'line': int, 'label': str | None, 'nest_level_at_start': int}]
        do_stack = []
        select_case_stack = [] # SELECT CASEブロックの開始行番号を格納

        for struct in structures:
            # 現在のネストレベルは、各スタックの合計長
            current_nest_level = len(if_stack) + len(do_stack) + len(select_case_stack)
            struct_with_nest = struct.copy()

            if struct['type'] == 'IF_BLOCK_START':
                if_stack.append(struct['line'])
            elif struct['type'] == 'ELSE_IF' or struct['type'] == 'ELSE':
                # ELSE/ELSE_IFは、親のIFブロックと同じネストレベルで表示されるべき
                # そのため、IFスタックの長さを1つ減らして計算
                if if_stack:
                    current_nest_level = len(if_stack) - 1 + len(do_stack) + len(select_case_stack)
                else:
                    # スタックが空の場合（エラーまたはメインルーチンのELSEなど）、最上位レベル
                    current_nest_level = len(do_stack) + len(select_case_stack)
                    logging.warning(f"Line {struct['line']}: ELSE/ELSE_IF found with empty IF stack.")
            elif struct['type'] == 'END_IF':
                if if_stack:
                    if_stack.pop()
                    current_nest_level = len(if_stack) + len(do_stack) + len(select_case_stack)
                else:
                    current_nest_level = 0 # スタックが空なのにEND IFがある場合、最上位レベル
                    logging.warning(f"Line {struct['line']}: END IF found with empty IF stack.")
            elif struct['type'] == 'DO_BLOCK_START':
                do_label = struct.get('label')
                # DOブロック開始時のネストレベルを記録
                do_stack.append({'line': struct['line'], 'label': do_label, 'nest_level_at_start': current_nest_level})
            elif struct['type'] == 'END_DO' or struct['type'] == 'CONTINUE_END_DO':
                if do_stack:
                    do_label_of_end = struct.get('label')
                    target_nest_level = 0 # ポップ後の目標ネストレベル

                    if do_label_of_end: # ラベル付きEND DO / CONTINUE の場合
                        # スタックを後ろから探索し、対応するラベルのDOを見つける
                        # Fortranでは同じラベルで複数のDOがネストしている場合、一番内側のDOから順に閉じられる
                        found_matching_do_idx = -1
                        for k in range(len(do_stack) - 1, -1, -1):
                            if do_stack[k].get('label') == do_label_of_end:
                                found_matching_do_idx = k
                                # 対応するDOの開始時のネストレベルを保存
                                target_nest_level = do_stack[k]['nest_level_at_start']
                                break
                        if found_matching_do_idx != -1:
                            # 見つかったDOからスタックの末尾まで全てポップ
                            popped_items = do_stack[found_matching_do_idx:]
                            do_stack = do_stack[:found_matching_do_idx]
                            logging.debug(f"Line {struct['line']}: Popping {len(popped_items)} DOs for label {do_label_of_end}. Current stack: {[d.get('label') for d in do_stack]}")
                        else:
                            # ラベルが見つからない場合はエラーだが、最も内側のDOをポップして不整合を防ぐ
                            logging.warning(f"Line {struct['line']}: Labeled DO termination (CONTINUE) for label {do_label_of_end} found, but no matching DO on stack. Popping innermost DO.")
                            if do_stack:
                                target_nest_level = do_stack[-1]['nest_level_at_start'] # ポップされるDOの開始時のネストレベル
                                do_stack.pop()
                            else:
                                target_nest_level = 0
                    else: # ラベルなしEND DOの場合、最も内側のDOをポップ
                        if do_stack:
                            target_nest_level = do_stack[-1]['nest_level_at_start'] # ポップされるDOの開始時のネストレベル
                            do_stack.pop()
                        else:
                            target_nest_level = 0
                        logging.debug(f"Line {struct['line']}: Popped unlabeled END DO. Current stack: {[d.get('label') for d in do_stack]}")

                    # 終了文自体のネストレベルは、それが閉じるブロックの開始ネストレベルと同じになる
                    current_nest_level = target_nest_level

                else:
                    current_nest_level = 0 # DOスタックが空なのにEND DO/CONTINUEがあった場合
                    logging.warning(f"Line {struct['line']}: {struct['type']} found with empty DO stack.")
            elif struct['type'] == 'SELECT_CASE_START':
                select_case_stack.append(struct['line'])
            elif struct['type'] == 'CASE':
                # CASEステートメントはSELECT CASEブロックの直下にあると見なす
                # したがって、ネストレベルは親のSELECT CASEと同じ（SELECT CASEのネストレベルにDO/IFを加える）
                if select_case_stack:
                    # SELECT_CASE_STARTのネストレベルは既に1つ加算されているため、CASEはその深さで表示
                    current_nest_level = len(if_stack) + len(do_stack) + len(select_case_stack)
                else:
                    current_nest_level = len(if_stack) + len(do_stack)
                    logging.warning(f"Line {struct['line']}: CASE found with empty SELECT CASE stack.")
            elif struct['type'] == 'END_SELECT':
                if select_case_stack:
                    select_case_stack.pop()
                    current_nest_level = len(if_stack) + len(do_stack) + len(select_case_stack)
                else:
                    current_nest_level = 0 # スタックが空なのにEND SELECTがあった場合、最上位レベル
                    logging.warning(f"Line {struct['line']}: END SELECT found with empty SELECT CASE stack.")
            
            # その他のステートメントは、この時点での計算されたネストレベルをそのまま使用
            
            struct_with_nest['nest_level'] = current_nest_level
            nested_structures.append(struct_with_nest)
        return nested_structures

    def export_analysis_data(self, output_filepath='flow_data.json'):
        """
        解析結果データをJSONファイルとして人間が読める形式で出力します。
        各ユニットの制御構造とそのネストレベルを表現します。
        Args:
            output_filepath (str): 出力JSONファイルのパス。
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
        CALL文を含まないDOループやIFブロック、不要なINCLUDE/宣言文、CALLを含まないI/O文は表示しません。
        Args:
            output_filepath (str): 出力テキストファイルのパス。
            indent_size (int): ネストレベルごとのインデントサイズ。
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
                    
                    # ユニット内の構造を処理するためのヘルパースタック
                    # 各要素はタプル: (構造体タイプ, ブロック開始行, ブロック終了行, 表示フラグ, オリジナルのネストレベル)
                    processing_stack = [] 
                    
                    # 後でブロックの表示/非表示を決定するために、事前にCALLの有無を判定
                    # 各ブロックの開始行をキーとして、そのブロック内にCALLがあるかを示すマップ
                    block_has_call_map = {} # {line_num_of_block_start: True/False}
                    
                    # 全体の構造を走査して、各ブロックがCALLを含むか判定
                    for i, struct in enumerate(unit['structures']):
                        current_type = struct['type']
                        current_line = struct['line']
                        current_nest_level = struct.get('nest_level', 0)

                        if current_type in ['DO_BLOCK_START', 'IF_BLOCK_START', 'SELECT_CASE_START']:
                            has_call_in_this_block = False
                            # このブロックの範囲内を検索
                            for j in range(i + 1, len(unit['structures'])):
                                inner_struct = unit['structures'][j]
                                if inner_struct['type'] == 'CALL':
                                    has_call_in_this_block = True
                                    break
                                # 現在のブロックのネストレベルと同じか浅くなったら、このブロックの範囲外
                                # ただし、論理IFやGOTOはネストレベルを変えずにブロックを抜ける可能性があるため、
                                # 終了を示すキーワードでより正確に判定する
                                if inner_struct.get('nest_level', 0) < current_nest_level or \
                                   (inner_struct.get('nest_level', 0) == current_nest_level and \
                                    inner_struct['type'] in ['END_DO', 'CONTINUE_END_DO', 'END_IF', 'END_SELECT', 'ELSE', 'ELSE_IF', 'RETURN', 'STOP', 'END', 'END_UNIT_STRICT']):
                                    break
                                
                            block_has_call_map[current_line] = has_call_in_this_block

                    # 実際のレポート生成ループ
                    for i, struct in enumerate(unit['structures']):
                        current_type = struct['type']
                        current_line = struct['line']
                        current_nest_level = struct.get('nest_level', 0)
                        original_content = struct['content']
                        content_to_display = original_content.strip()
                        
                        should_display = True # デフォルトは表示

                        # 1. 無視する行のフィルタリング (flow_report.txtのみ)
                        if current_type in ['PROGRAM_DECL', 'SUBROUTINE_DECL', 'FUNCTION_DECL', 'MODULE_DECL']:
                            should_display = False # ユニット宣言はヘッダーで表示済み
                        elif current_type == 'INCLUDE':
                            should_display = False # INCLUDE文は表示しない
                        elif current_type == 'LABEL':
                            # LABEL単独の行は基本的に表示しない (GOTOターゲットとしてフロー図に表示されるため)
                            # ただし、DO-CONTINUE のラベルは CONTINUE_END_DO として処理済み
                            # GOTOのターゲットになっているLABELは表示したい場合があるが、ここでは省略
                            should_display = False
                        elif current_type == 'OTHER_STATEMENT' and struct.get('is_noise'):
                            should_display = False # 宣言文や単純な代入文など
                        elif (self.re_patterns['io_statement_read'].match(original_content) or
                              self.re_patterns['io_statement_write'].match(original_content) or
                              self.re_patterns['io_statement_open_close'].match(original_content)) and \
                              not (current_type == 'CALL'): # CALLではないI/O文は表示しない
                            should_display = False
                        
                        # 2. DO/IFブロックの表示/非表示ロジック
                        if current_type in ['DO_BLOCK_START', 'IF_BLOCK_START', 'SELECT_CASE_START']:
                            # このブロックにCALLがあるかどうかで表示を決定
                            should_display = block_has_call_map.get(current_line, False)
                            
                            # 親ブロックが非表示であれば、このブロックも非表示
                            if processing_stack and not processing_stack[-1][1]:
                                should_display = False
                            
                            # スタックに積む
                            processing_stack.append((current_type, should_display, current_line, current_nest_level))

                        elif current_type in ['END_DO', 'END_IF', 'CONTINUE_END_DO', 'END_SELECT']:
                            # 対応する開始ブロックの表示フラグを継承し、スタックからポップ
                            # この終了文が属するブロックが非表示なら、この終了文も非表示にする
                            found_matching_block_display_flag = False
                            temp_stack = []
                            popped_any_relevant = False
                            
                            # スタックを逆順にたどり、対応する開始ブロックを見つける
                            while processing_stack:
                                # スタックトップを取得 (ポップは後で行う)
                                popped_type, popped_display_flag, popped_start_line, popped_nest_level = processing_stack[-1]

                                if popped_type == 'DO_BLOCK_START' and (current_type == 'END_DO' or current_type == 'CONTINUE_END_DO') and popped_nest_level == current_nest_level:
                                    # DO-ENDDO または DO-CONTINUE のマッチ
                                    # ラベル付きDOの場合、ラベルの一致も確認する方がより正確だが、
                                    # _calculate_nestingでスタックが正しく調整されている前提とする
                                    found_matching_block_display_flag = popped_display_flag
                                    popped_any_relevant = True
                                    break
                                elif popped_type == 'IF_BLOCK_START' and current_type == 'END_IF' and popped_nest_level == current_nest_level:
                                    # IF-ENDIF のマッチ
                                    found_matching_block_display_flag = popped_display_flag
                                    popped_any_relevant = True
                                    break
                                elif popped_type == 'SELECT_CASE_START' and current_type == 'END_SELECT' and popped_nest_level == current_nest_level:
                                    # SELECT CASE-END SELECT のマッチ
                                    found_matching_block_display_flag = popped_display_flag
                                    popped_any_relevant = True
                                    break
                                else:
                                    # 関係ないブロックまたはネストレベルが異なる場合は一旦退避
                                    temp_stack.append(processing_stack.pop())
                                    
                            if popped_any_relevant:
                                processing_stack.pop() # 実際にスタックから対応する開始ブロックをポップ
                                should_display = found_matching_block_display_flag
                            else:
                                # 対応する開始ブロックが見つからない場合、その終了文は非表示（または警告ログ）
                                should_display = False
                                logging.warning(f"Line {current_line}: {current_type} found without a matching start block on stack. Hidden in report.")

                            # 退避した要素を戻す
                            processing_stack.extend(reversed(temp_stack))

                        elif current_type in ['ELSE', 'ELSE_IF']:
                            # ELSE/ELSE_IFは直前のIFブロックと同じ表示フラグを継承
                            if processing_stack:
                                # IFスタックの最新のIFブロックの表示フラグを継承
                                found_if_block_display_flag = True # デフォルト
                                for item in reversed(processing_stack):
                                    if item[0] == 'IF_BLOCK_START':
                                        found_if_block_display_flag = item[1]
                                        break
                                should_display = found_if_block_display_flag
                            else:
                                should_display = True # スタックが空なら表示（エラーの可能性もあるが安全策）
                                logging.warning(f"Line {current_line}: {current_type} found with empty processing stack.")

                        elif current_type in ['RETURN', 'STOP', 'END', 'END_UNIT_STRICT']:
                            # ユニットの終了を示す文は常に表示（主要な構造として）
                            should_display = True
                            # ただし、もし直前のブロックが非表示であれば、この終了文も非表示にするか検討
                            # 今回は「主要な構造」として常に表示することに
                            if processing_stack and not processing_stack[-1][1]:
                                # ユニット全体の終了ではない場合、親の表示フラグに合わせる
                                should_display = processing_stack[-1][1]
                            elif not processing_stack and unit['type'] == 'PROGRAM_NONAME' and current_type == 'END':
                                should_display = True # 暗黙のプログラムの最後のENDは表示
                                

                        else: # その他のステートメント (CALL, LOGICAL_IF, OTHER_STATEMENT, GOTOなど)
                            # 現在のスタックのトップにあるブロックの表示フラグを継承
                            if processing_stack:
                                should_display = processing_stack[-1][1]
                            else:
                                should_display = True # 最上位のステートメントは常に表示

                        # 最終的な表示判定
                        if should_display:
                            indent = " " * (current_nest_level * indent_size)

                            # 表示内容を整形
                            display_content_info = content_to_display # デフォルト
                            if current_type == 'CALL':
                                display_content_info = f"CALL {struct.get('full_call_content', content_to_display)}"
                            elif current_type == 'LOGICAL_IF':
                                display_content_info = f"IF ({struct['condition']}) {struct['statement']}"
                            elif current_type == 'IF_BLOCK_START':
                                display_content_info = f"IF ({struct['condition']}) THEN"
                            elif current_type == 'ELSE_IF':
                                display_content_info = f"ELSE IF ({struct['condition']}) THEN"
                            elif current_type == 'ELSE':
                                display_content_info = "ELSE"
                            elif current_type == 'END_IF':
                                display_content_info = "END IF"
                            elif current_type == 'DO_BLOCK_START':
                                if 'label' in struct and struct['label']:
                                    display_content_info = f"DO {struct['label']} {content_to_display.replace(struct['label'], '', 1).strip()} (Loop: Start)"
                                else:
                                    display_content_info = f"DO {content_to_display.replace('DO ', '').strip()} (Loop: Start)"
                            elif current_type == 'END_DO':
                                display_content_info = f"END DO (Loop: End)"
                            elif current_type == 'CONTINUE_END_DO':
                                 if 'label' in struct and struct['label']:
                                     display_content_info = f"LABEL {struct['label']}: {content_to_display} (Loop: End)"
                                 else:
                                     display_content_info = f"CONTINUE (Loop: End)" # ラベルなしCONTINUEの場合
                            elif current_type == 'SELECT_CASE_START':
                                display_content_info = f"SELECT CASE ({struct['expression']})"
                            elif current_type == 'CASE':
                                display_content_info = f"CASE ({struct['value']})"
                            elif current_type == 'END_SELECT':
                                display_content_info = "END SELECT"
                            elif current_type == 'GOTO':
                                display_content_info = f"GOTO {struct['target_label']}"
                            elif current_type == 'RETURN':
                                display_content_info = "RETURN"
                            elif current_type == 'STOP':
                                display_content_info = "STOP"
                            elif current_type == 'LABEL': # ここに到達するLABELは孤立ラベル
                                display_content_info = f"LABEL {struct['label']}: {content_to_display}"
                            elif current_type == 'END_UNIT_STRICT':
                                display_content_info = f"END {unit['type']} (Strict)"
                            elif current_type == 'END':
                                display_content_info = "END"
                            # OTHER_STATEMENTはデフォルトの display_content_info でOK

                            f.write(f"{indent}L{current_line:<6} {display_content_info}\n")
                    f.write("\n")

            logging.info(f"ネストレベル付きテキストレポートを生成しました: {output_filepath}")
        except Exception as e:
            logging.error(f"テキストレポートの保存中にエラーが発生しました: {e}")

    def get_flow_relevant_structures(self):
        """
        フローチャートの描画に関連する構造のみをフィルタリングして返します。
        flow_report.txtのフィルタリングとは異なり、フローチャートに必要な全要素を含みます。
        Returns:
            dict: フローチャート関連構造のみを含む解析結果。
        """
        flow_relevant_core_types = [
            'IF_BLOCK_START', 'ELSE', 'ELSE_IF', 'END_IF',
            'DO_BLOCK_START', 'END_DO', 'CONTINUE_END_DO',
            'CALL', 'GOTO', 'LOGICAL_IF',
            'STOP', 'RETURN', 'END', 'END_UNIT_STRICT', # ユニット終了を示すもの
            'SELECT_CASE_START', 'CASE', 'END_SELECT',
            'LABEL', # GOTOターゲットとして必要
            'PROGRAM_DECL', 'SUBROUTINE_DECL', 'FUNCTION_DECL', 'MODULE_DECL', # ユニット宣言はフロー開始ノードとして必要
        ]
        
        filtered_units_data = []
        for unit in self.analysis_result['units']:
            filtered_structures = []
            for s in unit['structures']:
                # フロー図に直接関係するタイプはすべて含める
                if s['type'] in flow_relevant_core_types:
                    filtered_structures.append(s)
                elif s['type'] == 'OTHER_STATEMENT':
                    # OTHER_STATEMENTの中でも、フロー図に表示するべきもの（例: WRITE文などのIO操作）は含める
                    # ただし、宣言文や単純な代入文は除外
                    content_lower = s['content'].strip().lower()
                    if (self.re_patterns['io_statement_read'].match(content_lower) or
                        self.re_patterns['io_statement_write'].match(content_lower) or
                        self.re_patterns['io_statement_open_close'].match(content_lower)):
                        filtered_structures.append(s)
                    # その他のOTHER_STATEMENTは基本的に除外
                    # （必要であれば、ここにさらにルールを追加する）
                # INCLUDE文は通常フローチャートには含めないが、必要に応じてここに追加
                elif s['type'] == 'INCLUDE':
                    # INCLUDEも基本的にはフロー図から除外
                    continue
            
            # ソートし直すことで、行番号の順序を保証
            new_unit_data = unit.copy()
            new_unit_data['structures'] = sorted(filtered_structures, key=lambda x: x['line'])
            filtered_units_data.append(new_unit_data)
            
        return {"units": filtered_units_data}

