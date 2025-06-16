# fortran_analyzer.py

import re
import os
import collections
import json
import logging

class FortranAnalyzer:
    def __init__(self):
        self.re_patterns = {
            'program_unit_decl': re.compile(r"^\s*(PROGRAM|SUBROUTINE|FUNCTION|MODULE)\s+([a-zA-Z0-9_]+)", re.IGNORECASE),
            'end_unit': re.compile(r"^\s*END\s*(?:PROGRAM|SUBROUTINE|FUNCTION|MODULE)?\b", re.IGNORECASE),
            'call': re.compile(r"\bCALL\s+([a-zA-Z0-9_]+(?:\s*\(.*?\))?)", re.IGNORECASE), 
            'include': re.compile(r"^\s*INCLUDE\s*['\"](.+?)['\"]", re.IGNORECASE),
            'fixed_form_label': re.compile(r"^\s*(\d{1,5})\s*[^0-9\s]", re.IGNORECASE), 
            'block_if': re.compile(r"^\s*IF\s*\(.+\)\s*THEN", re.IGNORECASE),
            'logical_if': re.compile(r"^\s*IF\s*\((.+?)\)\s*(?!THEN)(.+)", re.IGNORECASE), 
            'else_if': re.compile(r"^\s*ELSE\s*IF\s*\(.+\)\s*THEN", re.IGNORECASE),
            'else': re.compile(r"^\s*ELSE\b", re.IGNORECASE),
            'end_if': re.compile(r"^\s*END\s*IF", re.IGNORECASE),
            'do': re.compile(r"^\s*DO(?:\s+\d+)?\s+.*", re.IGNORECASE), 
            'end_do': re.compile(r"^\s*END\s*DO|\s*(\d+)\s+CONTINUE", re.IGNORECASE), 
            'select_case': re.compile(r"^\s*SELECT\s+CASE\s*\(.+\)", re.IGNORECASE),
            'case': re.compile(r"^\s*CASE(?:\s*\(.+\))?", re.IGNORECASE), 
            'end_select': re.compile(r"^\s*END\s+SELECT", re.IGNORECASE),
            'goto': re.compile(r"^\s*GOTO\s+(\d+)", re.IGNORECASE),
            'return': re.compile(r"^\s*RETURN", re.IGNORECASE),
            'stop': re.compile(r"^\s*STOP", re.IGNORECASE),
            'comment_fixed_form': re.compile(r'^[C*!]', re.IGNORECASE), 
            'inline_comment': re.compile(r'!(.*)'), 
            'end': re.compile(r"^\s*END\b", re.IGNORECASE),  # 単独のEND文を認識
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
                if current_unit:
                    current_unit['end_line'] = line_num - 1
                
                unit_type, unit_name = match.groups()
                new_unit = {
                    'name': unit_name.upper(),
                    'type': unit_type.upper(),
                    'start_line': line_num,
                    'end_line': len(lines), # 仮の終了行
                    'structures': []
                }
                units.append(new_unit)
                current_unit = new_unit
                if unit_type.upper() == 'PROGRAM':
                    has_explicit_program = True
            
            elif self.re_patterns['end_unit'].match(code_part) or self.re_patterns['end'].match(code_part):
                if current_unit:
                    current_unit['end_line'] = line_num
                    current_unit = None

        # 最後のユニットの終了行を調整
        if current_unit:
            current_unit['end_line'] = len(lines)

        # PROGRAM宣言がない場合の「暗黙のメインプログラム」処理
        if not has_explicit_program and (not units or units[0]['start_line'] > 1):
            noname_program = {
                'name': 'PROGRAM_NONAME',
                'type': 'PROGRAM',
                'start_line': 1,
                'end_line': (units[0]['start_line'] - 1) if units else len(lines),
                'structures': []
            }
            units.insert(0, noname_program)
        elif not units and lines: # ファイル全体にユニット宣言がない場合
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
        """
        for unit in units:
            unit_lines_raw = lines[unit['start_line'] - 1 : unit['end_line']]
            if_stack = []  # IFブロックの情報を格納するスタック

            for i, raw_line in enumerate(unit_lines_raw):
                line_num = unit['start_line'] + i

                if self.re_patterns['comment_fixed_form'].match(raw_line):
                    continue
                
                code_part = self.re_patterns['inline_comment'].sub('', raw_line).strip()
                if not code_part:
                    continue

                processed_this_line = False

                # ラベルの検出
                label_match = self.re_patterns['fixed_form_label'].match(raw_line)
                if label_match:
                    label = label_match.group(1).strip()
                    unit['structures'].append({
                        'type': 'LABEL',
                        'line': line_num,
                        'label': label,
                        'content': raw_line.strip()
                    })
                
                # IFブロックの開始
                if self.re_patterns['block_if'].match(code_part):
                    if_info = {
                        'type': 'IF_BLOCK_START',
                        'line': line_num,
                        'condition': code_part[code_part.find('(')+1:code_part.rfind(')')].strip(),
                        'else_line': None,      # ELSE/ELSE IFの行番号を保持
                        'end_if_line': None,    # END IFの行番号を保持
                    }
                    if_stack.append(if_info)
                    unit['structures'].append(if_info)
                    processed_this_line = True
                
                # ELSE IF / ELSE
                elif self.re_patterns['else_if'].match(code_part) or self.re_patterns['else'].match(code_part):
                    if if_stack and if_stack[-1]['else_line'] is None:
                        if_stack[-1]['else_line'] = line_num

                    if self.re_patterns['else_if'].match(code_part):
                        unit['structures'].append({
                            'type': 'ELSE_IF',
                            'line': line_num,
                            'condition': code_part[code_part.find('(')+1:code_part.rfind(')')].strip()
                        })
                    else:
                        unit['structures'].append({
                            'type': 'ELSE',
                            'line': line_num,
                            'content': code_part
                        })
                    processed_this_line = True
                
                # END IF
                elif self.re_patterns['end_if'].match(code_part):
                    if if_stack:
                        if_info = if_stack.pop()
                        if_info['end_if_line'] = line_num
                    unit['structures'].append({
                        'type': 'END_IF',
                        'line': line_num
                    })
                    processed_this_line = True

                # CALL文
                elif self.re_patterns['call'].match(code_part):
                    call_match = self.re_patterns['call'].match(code_part)
                    unit['structures'].append({
                        'type': 'CALL',
                        'line': line_num,
                        'target': call_match.group(1).split('(')[0].strip().upper() # 引数部分を除外
                    })
                    processed_this_line = True
                
                # その他のステートメント (主要なもの)
                elif self.re_patterns['include'].match(code_part):
                    include_match = self.re_patterns['include'].match(code_part)
                    unit['structures'].append({
                        'type': 'INCLUDE',
                        'line': line_num,
                        'target': include_match.group(1).strip("'\""),
                        'content': code_part.strip()
                    })
                    processed_this_line = True
                elif self.re_patterns['logical_if'].match(code_part):
                    match = self.re_patterns['logical_if'].match(code_part)
                    unit['structures'].append({
                        'type': 'LOGICAL_IF',
                        'line': line_num,
                        'condition': match.group(1).strip(),
                        'statement': match.group(2).strip()
                    })
                    processed_this_line = True
                elif self.re_patterns['end'].match(code_part):
                     unit['structures'].append({'type': 'END', 'line': line_num})
                     processed_this_line = True
                elif self.re_patterns['stop'].match(code_part):
                    unit['structures'].append({'type': 'STOP', 'line': line_num})
                    processed_this_line = True

                # 上記以外で、まだ処理されていないコード行
                if not processed_this_line and code_part:
                    unit['structures'].append({
                        'type': 'OTHER_STATEMENT',
                        'line': line_num,
                        'content': code_part
                    })
            
            unit['structures'].sort(key=lambda x: x['line'])

    def _calculate_nesting(self, structures):
        """
        Fortranの制御構造に基づいて、各構造のネストレベルを計算します。
        """
        nested_structures = []
        if_stack = []          # 現在開いているIFブロックの開始行を格納
        do_stack = []          # 現在開いているDOループの開始行とターゲットラベルを格納
        select_case_stack = [] # 現在開いているSELECT CASEの開始行を格納

        for struct in structures:
            current_nest_level = len(if_stack) + len(do_stack) + len(select_case_stack)
            struct_with_nest = struct.copy()
            
            # スタック操作によるネストレベルの調整
            if struct['type'] == 'IF_BLOCK_START':
                if_stack.append(struct['line'])
            elif struct['type'] == 'ELSE_IF' or struct['type'] == 'ELSE':
                # ELSE IF / ELSE は、前のブロック (IF/ELSE IF) が終了し、新たなブロックが始まるため、
                # ネストレベル自体は減らさないが、現在のレベルで表示する
                # すでにif_stackにIFブロックが積まれている場合、そのレベルが現在のネストレベル
                # ただし、Mermaid生成時にはこのレベルが使われるため、内部は適切に調整される必要がある
                # ここでは、IF_BLOCK_STARTと同じレベルに設定し、内部はその下としてmermaid_generatorで調整
                if if_stack:
                    current_nest_level = len(if_stack) - 1 # 親IFのレベルに合わせる
                else:
                    current_nest_level = 0 # スタックが空の場合は0
            elif struct['type'] == 'END_IF':
                if if_stack:
                    if_stack.pop()
                    current_nest_level = len(if_stack) # ポップ後のレベル
                else:
                    current_nest_level = 0 # スタックが空の場合は0
            elif struct['type'] == 'DO_START':
                do_stack.append({'line': struct['line'], 'target_label': struct.get('target_label')})
            elif struct['type'] in ['END_DO', 'CONTINUE_END_DO']:
                if do_stack:
                    if struct.get('label'): # ラベル付きDOの場合
                        found = False
                        for k in range(len(do_stack) - 1, -1, -1):
                            if do_stack[k].get('target_label') == struct['label']:
                                do_stack.pop(k)
                                found = True
                                break
                        if not found:
                            logging.warning(f"行 {struct['line']}: ラベル {struct['label']} のDOループ終了に対応する開始が見つかりません。")
                    else: # ラベルなしDOの場合、最新のDOをポップ
                        do_stack.pop()
                    current_nest_level = len(do_stack) # ポップ後のレベル
                else:
                    current_nest_level = 0 # スタックが空の場合は0
            elif struct['type'] == 'SELECT_CASE_START':
                select_case_stack.append(struct['line'])
            elif struct['type'] == 'CASE': # CASE文はSELECT CASEブロックの内部だが、ネストレベルを増やす
                if select_case_stack:
                    current_nest_level = len(if_stack) + len(do_stack) + len(select_case_stack) # SELECT CASE自体のレベル
                else:
                    current_nest_level = 0
            elif struct['type'] == 'END_SELECT':
                if select_case_stack:
                    select_case_stack.pop()
                    current_nest_level = len(select_case_stack) + len(if_stack) + len(do_stack) # ポップ後のレベル
                else:
                    current_nest_level = 0
            
            # 論理IFはネストレベルに影響しない
            # 'LOGICAL_IF'はここでスタック操作をしないため、現在のネストレベルをそのまま使用

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

                        if struct['type'] == 'CALL':
                            content_info = f"CALL {struct['target']}"
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
                        elif struct['type'] == 'DO_START':
                            content_info = f"DO {struct.get('content', '')}"
                        elif struct['type'] in ['END_DO', 'CONTINUE_END_DO']:
                            content_info = f"{struct['type'].replace('_', ' ')} (Label: {struct['label'] if struct['label'] else 'N/A'})"
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
                            # LABELはMermaidでは独立したノードだが、テキストレポートではその行の内容として表示
                            content_info = f"LABEL {struct['label']}: {struct['content'].strip()}"
                        elif struct['type'] == 'OTHER_STATEMENT':
                            content_info = struct['content'].strip()
                        
                        f.write(f"{indent}{line_info:<8} {content_info}\n")
                    f.write("\n") # ユニット間の区切り

            logging.info(f"ネストレベル付きテキストレポートを生成しました: {output_filepath}")
        except Exception as e:
            logging.error(f"テキストレポートの保存中にエラーが発生しました: {e}")