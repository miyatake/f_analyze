import re
import logging
import json

class FortranAnalyzer:
    def __init__(self):
        self.analysis_data = {'units': []}
        self.logger = self._setup_logger()
        self.next_id = 0 # IDカウンターの初期化

        # --- 正規表現パターンの初期化とコンパイル ---
        # 継続行のパターン（削除：使用されていないため）
        # self.continuation_pattern = re.compile(r"^\s*(&|\+)\s*(.*)", re.IGNORECASE)

        # 固定形式コメントパターン (C, c, *, !)：Cとcとしているが、本来ならFortran/FORTRANともに大文字小文字を区別しないため、originallinws を保存して、全ての行でUpperCaseにすればよいはず。
        self.fixed_form_comment_pattern = re.compile(r"^\s*[Cc*!]")

        # 自由形式コメントパターン
        self.free_form_comment_pattern = re.compile(r"^\s*!")

        # Fortranの自由形式の場合、1桁目がCで始まるがコメントではない命令のリスト
        self.c_keywords_not_comment = [
            "CALL", "CHARACTER", "COMMON", "CONTINUE", "CYCLE", "CASE",
            "C_ASSOCIATED", "C_F_POINTER", "C_F_PROCPOINTER", "C_F_STRPOINTER",
            "C_FUNLOC", "C_LOC", "C_SIZEOF", "CACHESIZE", "CANCEL", "CANCELLATION",
            "CDFLOAT", "CEILING", "CFI_", "CHANGEDIRQQ", "CHANGEDRIVEQQ",
            "CHANGE_TEAM", "CHAR", "CHDIR", "CHMOD", "CLASS", "CLEARSTATUSFPQQ",
            "CLOCK", "CLOCKX", "CLOSE", "CMPLX", "CO_BROADCAST", "CO_MAX",
            "CO_MIN", "CO_REDUCE", "CO_SUM", "CODE_ALIGN", "CODIMENSION",
            "COLLAPSE", "COMMAND_ARGUMENT_COUNT", "COMMITQQ", "COTAN", "COTAND",
            "COUNT", "CPU_TIME", "CRITICAL", "CSHIFT", "CSMG", "CTIME",
            "CFI_ADDRESS", "CFI_ALLOCATE", "CFI_DEALLOCATE", "CFI_ESTABLISH",
            "CFI_IS_CONTIGUOUS", "CFI_SECTION", "CFI_SELECT_PART", "CFI_SETPOINTER"
        ]
        self.c_keywords_pattern = re.compile(r"^\s*(" + "|".join(re.escape(k) for k in self.c_keywords_not_comment) + r")\b", re.IGNORECASE)

        #'!'については、固定形式と自由形式の両方で、ソースコード内の任意の場所にある場合、それから後がコメントになるのでインラインコメントとして取得したい

        # UNIT開始のキーワード
        self.unit_start_keywords = {
            'PROGRAM': re.compile(r"^\s*(?:PROGRAM)\s*(\w+)?", re.IGNORECASE),
            'SUBROUTINE': re.compile(r"^\s*(?:SUBROUTINE)\s*(\w+)\s*(?:\(([^)]*)\))?", re.IGNORECASE),
            'FUNCTION': re.compile(r"^\s*(?:(?:REAL|INTEGER|COMPLEX|LOGICAL|CHARACTER(?:\*\d+)?|DOUBLE\s*PRECISION)\s*)?(?:FUNCTION)\s*(\w+)\s*(?:\(([^)]*)\))?", re.IGNORECASE),
            'MODULE': re.compile(r"^\s*(?:MODULE)\s*(\w+)", re.IGNORECASE),
            'BLOCK DATA': re.compile(r"^\s*(?:BLOCK\s*DATA)(?:\s*(\w+))?", re.IGNORECASE)
        }

        # UNIT終了のキーワード：固定形式・自由形式共にほとんどのケースで空白を除去したケースでも一致するか確認する必要がある。
        self.unit_end_keywords = {
            'END PROGRAM': re.compile(r"^\s*END\s*PROGRAM(?:\s*(\w+))?", re.IGNORECASE),
            'END SUBROUTINE': re.compile(r"^\s*END\s*SUBROUTINE(?:\s*(\w+))?", re.IGNORECASE),
            'END FUNCTION': re.compile(r"^\s*END\s*FUNCTION(?:\s*(\w+))?", re.IGNORECASE),
            'END MODULE': re.compile(r"^\s*END\s*MODULE(?:\s*(\w+))?", re.IGNORECASE),
            'END BLOCK DATA': re.compile(r"^\s*END\s*BLOCK\s*DATA(?:\s*(\w+))?", re.IGNORECASE),
            'END': re.compile(r"^\s*END(?!\s*(?:DO|IF|SELECT|WHERE|TYPE)\b)", re.IGNORECASE) # ENDキーワードだが特定のキーワードとは結合しない
        }

        # 構造化された制御文の開始キーワード
        self.block_start_keywords = {
            'DO': re.compile(r"^\s*(?:(\d+)\s*)?DO(?!\s*WHILE)\b(?:\s*(\w+)\s*=\s*.*)?", re.IGNORECASE), # DO (ラベル付き/なし, 制御変数あり/なし)
            'DO WHILE': re.compile(r"^\s*DO\s*WHILE\s*\((.*)\)", re.IGNORECASE),
            'IF': re.compile(r"^\s*IF\s*\((.*)\)\s*THEN", re.IGNORECASE),
            'SELECT CASE': re.compile(r"^\s*SELECT\s*CASE\s*\((.*)\)", re.IGNORECASE)
        }

        # 構造化された制御文の終了キーワード
        self.block_end_keywords = {
            'END DO': re.compile(r"^\s*END\s*DO", re.IGNORECASE),
            'END IF': re.compile(r"^\s*END\s*IF", re.IGNORECASE),
            'END SELECT': re.compile(r"^\s*END\s*SELECT", re.IGNORECASE)
        }

        # 論理IF文 (1行IF)
        self.logical_if_pattern = re.compile(r"^\s*IF\s*\((.*)\)\s*([^!]+)", re.IGNORECASE)

        # その他の制御フロー、IO、宣言など
        self.other_keywords = {
            'ELSE IF': re.compile(r"^\s*ELSE\s*IF\s*\((.*)\)\s*THEN", re.IGNORECASE),
            'ELSE': re.compile(r"^\s*ELSE", re.IGNORECASE),
            'CALL': re.compile(r"^\s*CALL\s*(\w+)(?:\s*\(([^)]*)\))?", re.IGNORECASE),
            'GOTO': re.compile(r"^\s*GO\s*TO\s*(\d+)", re.IGNORECASE),
            'STOP': re.compile(r"^\s*STOP", re.IGNORECASE),
            'RETURN': re.compile(r"^\s*RETURN", re.IGNORECASE),
            'CONTINUE': re.compile(r"^\s*CONTINUE", re.IGNORECASE), # 単独のCONTINUE
            'READ': re.compile(r"^\s*READ(?:\s*\(.*?\))?", re.IGNORECASE),
            'WRITE': re.compile(r"^\s*WRITE(?:\s*\(.*?\))?", re.IGNORECASE),
            'OPEN': re.compile(r"^\s*OPEN(?:\s*\(.*?\))?", re.IGNORECASE),
            'CLOSE': re.compile(r"^\s*CLOSE(?:\s*\(.*?\))?", re.IGNORECASE),
            'INQUIRE': re.compile(r"^\s*INQUIRE(?:\s*\(.*?\))?", re.IGNORECASE),
            'REWIND': re.compile(r"^\s*REWIND(?:\s*\(.*?\))?", re.IGNORECASE),
            'BACKSPACE': re.compile(r"^\s*BACKSPACE(?:\s*\(.*?\))?", re.IGNORECASE),
            'ENDFILE': re.compile(r"^\s*ENDFILE(?:\s*\(.*?\))?", re.IGNORECASE),
            'FORMAT': re.compile(r"^\s*FORMAT\s*\(.*\)", re.IGNORECASE),
            'INCLUDE': re.compile(r"^\s*INCLUDE\s*['\"](.*?)['\"]", re.IGNORECASE)
        }

        # 宣言文の一般的なパターン (より汎用的に)
        self.declaration_pattern = re.compile(
            r"^\s*(?:REAL|INTEGER|COMPLEX|LOGICAL|CHARACTER(?:\s*\*\s*\d+)?|DOUBLE\s*PRECISION|TYPE|PARAMETER|COMMON|EXTERNAL|INTRINSIC|DATA|DIMENSION|SAVE|EQUIVALENCE|POINTER|ALLOCATABLE|TARGET)\b",
            re.IGNORECASE
        )

        # 固定形式で1-5桁目にラベルがある場合のパターン (FORMAT文を除く)
        self.label_pattern = re.compile(r"^\s*(\d+)\s*(?!\s*FORMAT)", re.IGNORECASE)

    def _setup_logger(self):
        logger = logging.getLogger('FortranAnalyzer')
        logger.setLevel(logging.INFO) # デバッグメッセージを見る場合は logging.DEBUG に変更
        # StreamHandlerは追加しない（main.pyで設定済みなので）
        return logger

    def generate_id(self):
        """ユニークなIDを生成し、返します。"""
        self.next_id += 1
        return self.next_id

    def _get_indent_level(self, line):
        """行のインデントレベルを推測する (半角スペース4つを1レベルとする)"""
        if not line.strip():
            return 0
        
        # 固定形式の場合、最初の6文字はラベル領域なので無視
        # 6カラム目が空白または'0' (コメント行ではないことを意味する)
        if len(line) >= 6 and (line[5] == ' ' or line[5] == '0'): 
             # 7カラム目以降のインデントを計算
            return (len(line[6:]) - len(line[6:].lstrip(' '))) // 4
        else: # 自由形式の場合、行頭からのインデントを計算
            return (len(line) - len(line.lstrip(' '))) // 4

    def _preprocess_lines(self, code_lines):
        """
        継続行を含めて論理行ごとにまとめ、各論理行に物理行情報・id・継続行種別・type（初期値'CODE'）などを付与して返す。
        """
        logical_lines_data = []
        i = 0
        current_id = 0
        while i < len(code_lines):
            line = code_lines[i]
            original_line = line
            processed_line = line.lstrip()
            processed_line_no_newline = processed_line.rstrip('\r\n')
            is_fixed_form_continuation = False
            is_free_form_continuation = False
            # 空行判定
            if not original_line.strip():
                logical_lines_data.append({
                    'logical_content': '',
                    'original_content': original_line.rstrip('\n'),
                    'physical_line_nums': [i+1],
                    'id': current_id,
                    'continuation_type': None,
                    'type': 'blank_line',
                    'label': None,
                })
                current_id += 1
                i += 1
                continue
            # コメント行判定（固定形式の厳密化）
            is_fixed_form_comment = False
            if len(original_line) > 0 and original_line[0] in ('c', 'C', '*', '!'):
                # 6カラム目以降にCALLやSUBROUTINE等のキーワードがあればコード扱い
                code_part = original_line[6:].lstrip() if len(original_line) > 6 else ''
                is_code_keyword = False
                for key, pattern in list(self.unit_start_keywords.items()) + list(self.other_keywords.items()):
                    if pattern.match(code_part):
                        is_code_keyword = True
                        break
                if not is_code_keyword:
                    is_fixed_form_comment = True
            if is_fixed_form_comment or self.free_form_comment_pattern.match(original_line):
                logical_lines_data.append({
                    'logical_content': '',  # コメント行は空文字列
                    'original_content': original_line.rstrip('\n'),
                    'physical_line_nums': [i+1],
                    'id': current_id,
                    'continuation_type': None,
                    'type': 'comment_line',
                    'label': None,
                })
                current_id += 1
                i += 1
                continue
            # インラインコメント除去
            code_part = original_line.split('!')[0] if '!' in original_line else original_line
            processed_line = code_part.rstrip().lstrip()
            processed_line_no_newline = processed_line.rstrip('\r\n')
            # 固定形式継続行判定
            if len(line) >= 6 and line[5] not in (' ', '0'):
                is_fixed_form_continuation = True
            # 自由形式継続行判定
            if processed_line_no_newline.endswith('&'):
                is_free_form_continuation = True
            # 継続行バッファ
            if is_fixed_form_continuation or is_free_form_continuation:
                buffer_lines = [original_line]
                buffer_line_nums = [i+1]
                if is_fixed_form_continuation:
                    line_buffer = original_line[6:]
                    line_buffer = line_buffer.split('!')[0].lstrip().rstrip('\n') if '!' in line_buffer else line_buffer.lstrip().rstrip('\n')
                    continuation_type = 'FIXED_FORM'
                else:
                    line_buffer = processed_line_no_newline[:-1]
                    line_buffer = line_buffer.split('!')[0].lstrip() if '!' in line_buffer else line_buffer.lstrip()
                    continuation_type = 'FREE_FORM'
                # 継続行の行頭が「&」で始まる場合の警告
                if processed_line.lstrip().startswith('&'):
                    self.logger.warning(f"物理行 {i+1} : 継続行の行頭が「&」で始まっています。Fortranの仕様上、前後の空白や連結に注意してください。")
                j = i + 1
                while j < len(code_lines):
                    next_line = code_lines[j]
                    next_processed = next_line.lstrip()
                    next_processed_no_newline = next_processed.rstrip('\r\n')
                    next_is_fixed_continuation = len(next_line) >= 6 and next_line[5] not in (' ', '0')
                    next_is_free_continuation = next_processed_no_newline.endswith('&')
                    next_is_free_form_continuation_continuation = (len(next_line) >= 6 and next_line[5] == ' ' and 
                                                                  next_processed_no_newline and not next_processed_no_newline.startswith('!') and
                                                                  is_free_form_continuation and j == i + 1)
                    if next_is_fixed_continuation:
                        next_buffer = next_line[6:]
                        next_buffer = next_buffer.split('!')[0].lstrip().rstrip('\n') if '!' in next_buffer else next_buffer.lstrip().rstrip('\n')
                        line_buffer += next_buffer
                        buffer_lines.append(next_line)
                        buffer_line_nums.append(j+1)
                        # 継続行の行頭が「&」で始まる場合の警告
                        if next_processed.lstrip().startswith('&'):
                            self.logger.warning(f"物理行 {j+1} : 継続行の行頭が「&」で始まっています。Fortranの仕様上、前後の空白や連結に注意してください。")
                    elif next_is_free_continuation or next_is_free_form_continuation_continuation:
                        next_buffer = next_processed_no_newline[:-1]
                        next_buffer = next_buffer.split('!')[0].lstrip() if '!' in next_buffer else next_buffer.lstrip()
                        line_buffer += next_buffer
                        buffer_lines.append(next_line)
                        buffer_line_nums.append(j+1)
                        # 継続行の行頭が「&」で始まる場合の警告
                        if next_processed.lstrip().startswith('&'):
                            self.logger.warning(f"物理行 {j+1} : 継続行の行頭が「&」で始まっています。Fortranの仕様上、前後の空白や連結に注意してください。")
                    else:
                        break
                    j += 1
                # 継続行の最終行に到達した際の警告
                last_physical_line_num = buffer_line_nums[-1]
                last_physical_line_content = buffer_lines[-1].rstrip('\n')
                self.logger.warning(f"継続行の最終行に到達: 物理行 {last_physical_line_num} : '{last_physical_line_content}'")
                logical_lines_data.append({
                    'logical_content': line_buffer,
                    'original_content': '\n'.join(buffer_lines),
                    'physical_line_nums': buffer_line_nums,
                    'id': current_id,
                    'continuation_type': continuation_type,
                    'type': 'CODE',
                    'label': None,
                })
                current_id += 1
                i = j
            else:
                logical_lines_data.append({
                    'logical_content': processed_line,  # インラインコメント除去済み
                    'original_content': original_line.rstrip('\n'),
                    'physical_line_nums': [i+1],
                    'id': current_id,
                    'continuation_type': None,
                    'type': 'CODE',
                    'label': None,
                })
                current_id += 1
                i += 1
        return logical_lines_data

    def _identify_units_and_labels(self, logical_lines_data, all_code_lines_for_original_content):
        """
        プログラムユニットと、各ユニット内のラベルを特定するフェーズ。
        このフェーズでは、ブロック構造の対応付けは行わない。
        """
        current_unit_data = None
        first_unit_found = False
        for idx, item in enumerate(logical_lines_data):
            current_physical_line_num = item['physical_line_nums'][0]
            full_logical_line = item['logical_content']
            original_line_content = item['original_content']
            line_type = item['type']
            label_num_from_preprocess = item.get('label') # _preprocess_linesで抽出されたラベル

            # コメントはここでユニットに追加しない。_analyze_unit_structuresで適切なインデントで追加される。
            if line_type in ['COMMENT', 'comment_line', 'BLANK', 'blank_line']:
                continue
            
            # 論理行からラベル部分を除去（マッチング用）
            line_without_label = full_logical_line
            if label_num_from_preprocess:
                match_label_removal = self.label_pattern.match(full_logical_line)
                if match_label_removal:
                    line_without_label = self.label_pattern.sub("", full_logical_line, 1).strip()

            # 仮ユニット追加（最初のユニット宣言検出時）
            if not first_unit_found:
                for unit_type, pattern in self.unit_start_keywords.items():
                    match = pattern.match(line_without_label)
                    if match:
                        first_unit_found = True
                        # もし先頭に仮ユニットがまだなければ、ここまでの行を仮ユニットとして追加
                        if not self.analysis_data['units']:
                            pre_unit_lines = logical_lines_data[:idx]
                            if pre_unit_lines:
                                dummy_unit = {
                                    'id': self.generate_id(),
                                    'name': 'MAIN_PROGRAM',
                                    'type': 'PROGRAM_NONAME',
                                    'start_line': pre_unit_lines[0]['physical_line_nums'][0],
                                    'end_line': pre_unit_lines[-1]['physical_line_nums'][-1],
                                    'args': None,
                                    'labels': {},
                                    'raw_statements': []
                                }
                                for pre_item in pre_unit_lines:
                                    dummy_unit['raw_statements'].append({
                                        'physical_line_num': pre_item['physical_line_nums'][0],
                                        'logical_content': pre_item['logical_content'],
                                        'original_content': pre_item['original_content'],
                                        'label': pre_item.get('label'),
                                        'type': pre_item['type'],
                                    })
                                self.analysis_data['units'].append(dummy_unit)
                                self.logger.info(f"仮ユニット追加: {dummy_unit['id']} {dummy_unit['name']} (行: {dummy_unit['start_line']}-{dummy_unit['end_line']})")
                        # breakやcontinueはしない
            # ここで必ず既存のユニット宣言検出・追加ロジックを実行
            unit_found = False
            for unit_type, pattern in self.unit_start_keywords.items():
                match = pattern.match(line_without_label)
                if match:
                    unit_name = match.group(1) if match.group(1) else f"NONAME_{unit_type.replace(' ', '_')}"
                    unit_args = match.group(2) if len(match.groups()) > 1 and match.group(2) else ""

                    # 既存のユニットを終了させる
                    if current_unit_data:
                        current_unit_data['end_line'] = current_physical_line_num - 1
                        self.logger.info(f"ユニット終了　　　: {current_unit_data['id']:<3}{current_unit_data['name']} (行: {current_unit_data['start_line']}-{current_unit_data['end_line']})")
                        end_line_original_content = all_code_lines_for_original_content[current_unit_data['end_line'] - 1].strip() if current_unit_data['end_line'] > 0 else ""
                        current_unit_data['raw_statements'].append({
                            'physical_line_num': current_unit_data['end_line'],
                            'logical_content': logical_lines_data[current_unit_data['end_line']-1]['logical_content'] if current_unit_data['end_line']-1 < len(logical_lines_data) else '',
                            'original_content': all_code_lines_for_original_content[current_unit_data['end_line'] - 1] if current_unit_data['end_line'] > 0 else '',
                            'type': 'UNIT_END_PLACEHOLDER',
                            'unit_type_name': current_unit_data['type']
                        })

                    current_unit_data = {
                        'id': self.generate_id(),
                        'name': unit_name,
                        'type': unit_type.replace(' ', '_').upper(),
                        'start_line': current_physical_line_num,
                        'end_line': -1,
                        'args': unit_args,
                        'labels': {},
                        'raw_statements': []
                    }
                    self.analysis_data['units'].append(current_unit_data)
                    self.logger.info(f"ユニット開始　　　: {current_unit_data['id']:<3}{current_unit_data['name']} ({current_unit_data['type']}) (行: {current_physical_line_num})")
                    current_unit_data['raw_statements'].append({
                        'physical_line_num': current_physical_line_num,
                        'logical_content': item['logical_content'],
                        'original_content': item['original_content'],
                        'label': label_num_from_preprocess,
                        'type': 'UNIT_DECLARATION_RAW',
                        'unit_type': unit_type.replace(' ', '_').upper(),
                        'name': unit_name,
                        'args': unit_args
                    })
                    unit_found = True
                    if self.analysis_data['units'] and self.analysis_data['units'][0]['type'] == 'PROGRAM_NONAME' and self.analysis_data['units'][0]['end_line'] == -1:
                        self.analysis_data['units'][0]['end_line'] = current_physical_line_num - 1
                        self.logger.info(f"暗黙のユニット終了: {current_unit_data['id']:<3}{self.analysis_data['units'][0]['name']} (行: {self.analysis_data['units'][0]['start_line']}-{self.analysis_data['units'][0]['end_line']})")
                        main_end_line_original_content = all_code_lines_for_original_content[self.analysis_data['units'][0]['end_line'] - 1].strip() if self.analysis_data['units'][0]['end_line'] > 0 else ""
                        self.analysis_data['units'][0]['raw_statements'].append({
                            'physical_line_num': self.analysis_data['units'][0]['end_line'],
                            'logical_content': logical_lines_data[self.analysis_data['units'][0]['end_line']-1]['logical_content'] if self.analysis_data['units'][0]['end_line']-1 < len(logical_lines_data) else '',
                            'original_content': all_code_lines_for_original_content[self.analysis_data['units'][0]['end_line'] - 1] if self.analysis_data['units'][0]['end_line'] > 0 else '',
                            'type': 'UNIT_END_PLACEHOLDER',
                            'unit_type_name': 'PROGRAM_NONAME'
                        })
            if unit_found:
                pass  # continueせず、ユニット本体のraw_statements追加処理を必ず実行

            # ユニット内にいる場合のみ、ステートメントとラベルを収集
            if current_unit_data:
                # ラベルを現在のユニットのスコープに登録
                if label_num_from_preprocess:
                    current_unit_data['labels'][label_num_from_preprocess] = current_physical_line_num
                    self.logger.debug(f"ユニット '{current_unit_data['name']}' にラベル '{label_num_from_preprocess}' (行: {current_physical_line_num}) を追加")

                # UNITの終了を検出 (END PROGRAM, END SUBROUTINEなど)
                end_unit_found = False
                for unit_type_end, pattern_end in self.unit_end_keywords.items():
                    match_end = pattern_end.match(line_without_label)
                    if match_end:
                        if current_unit_data:
                            final_unit_type_name = unit_type_end.replace('END ', '').replace(' ', '_').upper()
                            if final_unit_type_name == 'END' and current_unit_data['type'] != 'UNKNOWN':
                                final_unit_type_name = current_unit_data['type']
                            current_unit_data['end_line'] = current_physical_line_num
                            current_unit_data['raw_statements'].append({
                                'physical_line_num': current_physical_line_num,
                                'logical_content': item['logical_content'],
                                'original_content': item['original_content'],
                                'type': 'UNIT_END_RAW',
                                'unit_type': final_unit_type_name
                            })
                            self.logger.info(f"ユニット終了　　　: {current_unit_data['id']:<3}{current_unit_data['name']} (行: {current_unit_data['start_line']}-{current_unit_data['end_line']})")
                            current_unit_data = None
                        end_unit_found = True
                        break
                if end_unit_found:
                    continue

                # その他のコード行は raw_statements に追加
                stmt_type = 'CODE_STATEMENT_RAW'
                if line_type == 'comment_line':
                    stmt_type = 'COMMENT'
                elif line_type == 'blank_line':
                    stmt_type = 'BLANK'
                current_unit_data['raw_statements'].append({
                    'physical_line_num': current_physical_line_num,
                    'logical_content': item['logical_content'],
                    'original_content': item['original_content'],
                    'label': label_num_from_preprocess,
                    'type': stmt_type
                })

    def _analyze_unit_structures(self):
        """
        各プログラムユニット内のraw_statements（論理行）を詳細に解析し、type, target, args, indent_levelなどの属性を直接上書きする。
        """
        for unit_data in self.analysis_data['units']:
            structure_stack = []
            for stmt in unit_data['raw_statements']:
                full_logical_line = stmt['logical_content']
                if not full_logical_line:
                    continue
                # インデントレベル（ネスト深さ）
                stmt['indent_level'] = len(structure_stack)
                # CALL文
                m = re.match(r'^\s*CALL\s+([A-Za-z0-9_]+)\s*(?:\(([^)]*)\))?', full_logical_line, re.IGNORECASE)
                if m:
                    stmt['type'] = 'CALL'
                    stmt['target'] = m.group(1)
                    stmt['args'] = m.group(2) if m.group(2) else ''
                    continue
                # GOTO文
                m = re.match(r'^\s*GOTO\s+(\d+)', full_logical_line, re.IGNORECASE)
                if m:
                    stmt['type'] = 'GOTO'
                    stmt['target_label'] = m.group(1)
                    continue
                # IF文
                m = re.match(r'^\s*IF\s*\((.*?)\)\s*THEN', full_logical_line, re.IGNORECASE)
                if m:
                    stmt['type'] = 'IF_BLOCK_START'
                    stmt['condition'] = m.group(1)
                    structure_stack.append('IF')
                    continue
                # DO文
                m = re.match(r'^\s*DO\s*(\d+)?\s*(.*)', full_logical_line, re.IGNORECASE)
                if m:
                    stmt['type'] = 'DO_BLOCK_START'
                    stmt['label'] = m.group(1) if m.group(1) else None
                    structure_stack.append('DO')
                    continue
                # END IF
                if re.match(r'^\s*END\s*IF', full_logical_line, re.IGNORECASE):
                    stmt['type'] = 'END_IF'
                    if structure_stack and structure_stack[-1] == 'IF':
                        structure_stack.pop()
                    stmt['indent_level'] = len(structure_stack)  # pop後の値に修正
                    continue
                # END DO
                if re.match(r'^\s*END\s*DO', full_logical_line, re.IGNORECASE):
                    stmt['type'] = 'DO_BLOCK_END'
                    if structure_stack and structure_stack[-1] == 'DO':
                        structure_stack.pop()
                    stmt['indent_level'] = len(structure_stack)  # pop後の値に修正
                    continue
                # LOGICAL IF文（1行IF）
                m = re.match(r'^\s*IF\s*\((.*?)\)\s*(.+)$', full_logical_line, re.IGNORECASE)
                if m and not full_logical_line.strip().upper().endswith('THEN'):
                    stmt['type'] = 'LOGICAL_IF'
                    stmt['condition'] = m.group(1)
                    stmt['statement'] = m.group(2)
                    continue
                # 代入文
                m = re.match(r"^\s*(\w+\s*\(?[\w,]*\)?\s*)=\s*(.*)", full_logical_line)
                if m:
                    stmt['type'] = 'ASSIGNMENT_STATEMENT'
                    continue
                # その他キーワード判定
                for key, pattern in self.other_keywords.items():
                    m = pattern.match(full_logical_line)
                    if m:
                        if key in ['READ', 'WRITE', 'OPEN', 'CLOSE', 'INQUIRE', 'REWIND', 'BACKSPACE', 'ENDFILE']:
                            stmt['type'] = 'IO_OPERATION'
                            stmt['operation_type'] = key
                        elif key == 'ELSE IF':
                            stmt['type'] = 'ELSE_IF'
                        elif key == 'ELSE':
                            stmt['type'] = 'ELSE'
                        elif key == 'CALL':
                            stmt['type'] = 'CALL'
                            stmt['target'] = m.group(1)
                            stmt['args'] = m.group(2) if len(m.groups()) > 1 and m.group(2) else ''
                        elif key == 'GOTO':
                            stmt['type'] = 'GOTO'
                            stmt['target_label'] = m.group(1)
                        elif key == 'STOP':
                            pass
                        elif key == 'RETURN':
                            pass
                        elif key == 'CONTINUE':
                            stmt['type'] = 'CONTINUE_STATEMENT'
                        elif key == 'FORMAT':
                            stmt['type'] = 'FORMAT'
                        elif key == 'INCLUDE':
                            stmt['type'] = 'INCLUDE'
                            stmt['target'] = m.group(1)
                        break

    def analyze(self, code_lines):
        """
        Fortranコードを分析するメインメソッド。
        二段階解析プロセスを実行する。
        """
        self.analysis_data = {'units': []}
        self.next_id = 0

        # フェーズ1: 継続行の結合とユニット・ラベルの特定
        logical_lines_data = self._preprocess_lines(code_lines)
        self._identify_units_and_labels(logical_lines_data, code_lines) # original code linesも渡す
        
        # フェーズ2: 各ユニット内の詳細な構造解析
        self._analyze_unit_structures()

#        self.logger.info("--- 解析結果サマリー ---")
        return self.analysis_data

    def export_analysis_data(self, output_filepath):
        """
        解析データをJSON形式で出力する。各ユニットのraw_statements（論理行リスト）を必ず'statements'キーで出力する。
        """
        export_data = {'units': []}
        for unit in self.analysis_data['units']:
            unit_copy = dict(unit)
            unit_copy.pop('structures', None)
            # 必ず'statements'キーを持たせる
            if 'raw_statements' in unit_copy:
                unit_copy['statements'] = unit_copy.pop('raw_statements')
            elif 'statements' not in unit_copy:
                unit_copy['statements'] = []
            export_data['units'].append(unit_copy)
        with open(output_filepath, 'w', encoding='utf-8') as f:
            json.dump(export_data, f, ensure_ascii=False, indent=2)

    def generate_nested_text_report(self, output_filepath):
        try:
            with open(output_filepath, 'w', encoding='utf-8') as f:
                for unit in self.analysis_data['units']:
                    unit_display_type = unit['type'].replace('_NONAME', '').replace('_', ' ')
                    unit_name = unit['name']
                    unit_start_line = unit['start_line']
                    unit_end_line = unit['end_line']
                    unit_args = unit['args']
                    
                    f.write(f"=== {unit_display_type}: {unit_name} (Lines: {unit_start_line}-{unit_end_line}) ===\n")
                    if unit_args:
                        f.write(f"Arguments: {unit_args}\n")
                    
                    # 構造体をline_numでソート
                    sorted_statements = sorted(unit['raw_statements'], key=lambda x: x['physical_line_num'])

                    for item in sorted_statements:
                        line_num = item['physical_line_num']
                        indent = "    " * item.get('indent_level', 0)
                        line_content_stripped = item['logical_content'].strip() if 'logical_content' in item else ''
                        t = item['type']
                        # コメント・INCLUDEはスキップ
                        if t in ['COMMENT', 'INCLUDE']:
                            continue
                        # CALL, IF/ELSE/ENDIF, DO, GOTO, STOP, RETURN, END, LOGICAL_IF, END_IF, DO_BLOCK_ENDは常に出力
                        always_output_types = [
                            'CALL', 'IF_BLOCK_START', 'ELSE_IF', 'ELSE', 'IF_BLOCK_END',
                            'DO_BLOCK_START', 'DO_BLOCK_END', 'LOGICAL_IF',
                            'GOTO', 'STOP', 'RETURN', 'END', 'DO_WHILE_START', 'DO_BLOCK_END_LABEL_CONTINUE', 'END_IF',
                            'UNIT_END_RAW', 'UNIT_END'  # 追加: END文のtype
                        ]
                        # ASSIGNMENT_STATEMENT, IO_OPERATIONはブロック内（インデント1以上）のみ出力
                        if t in always_output_types:
                            pass
                        elif t in ['ASSIGNMENT_STATEMENT', 'IO_OPERATION']:
                            if item.get('indent_level', 0) < 1:
                                continue
                        else:
                            continue
                        # UNIT_ENDで内容が空の場合も表示できるように修正
                        if not line_content_stripped and t not in ['UNIT_END', 'UNIT_END_RAW']:
                            continue
                        id_info = f"" # ID情報は未使用
                        report_line = f"{indent}L{line_num}: {line_content_stripped}"
                        if t == 'UNIT_DECLARATION':
                            report_line = f"L{line_num}: {item['unit_type']} {item['name']}"
                            if item['args']:
                                report_line += f"({item['args']})"
                        elif t in ['UNIT_END', 'UNIT_END_RAW']:
                            display_content = item.get('line_content', '').strip() if item.get('line_content', '').strip() else f"END {item.get('unit_type', '').replace('_', ' ')}"
                            report_line = f"L{line_num}: {display_content}"
                        # それ以外は説明文なし
                        f.write(report_line + id_info + "\n")
                    f.write("\n")

            self.logger.info(f"ネストレベル付きレポートが '{output_filepath}' に生成されました。")
        except Exception as e:
            self.logger.error(f"レポート生成中にエラーが発生しました: {e}")

# 使用例 (この部分はファイルには含めず、テスト用として使用)
if __name__ == "__main__":
    fortran_code_example = [
        "      INTEGER :: I, J",  # 1
        "      REAL X",          # 2
        " 10   FORMAT (I5)",     # 3
        "      DO 100 I = 1, 10", # 4 (Outer DO 100)
        "         DO 100 j = 1, 10", # 5 (Inner DO 100)
        "         IF (I .EQ. 5) THEN", # 6
        "            CALL SUB1(I, J)", # 7
        "         ELSE IF (I .EQ. 7) THEN", # 8
        "            WRITE(*,10) 'I is 7'", # 9
        "         ELSE", # 10
        "            X = REAL(I) * 2.0", # 11
        "         END IF", # 12
        "         J = I + 1", # 13
        " 100  CONTINUE", # 14 (Closes both DO 100 I and DO 100 J)
        "      STOP", # 15
        "      END",  # 16
        "      SUBROUTINE SUB1(A, B)", # 17
        "      INTEGER A, B", # 18
        "      IF (A .GT. 0) GOTO 20", # 19
        "      PRINT *, 'A is not positive'", # 20
        " 100   CONTINUE", # 21 (This label 100 is different from the one in MAIN_PROGRAM)
        "      RETURN", # 22
        "      END SUBROUTINE SUB1", # 23
        "      FUNCTION MYFUNC(K)", # 24
        "      INTEGER K, MYFUNC", # 25
        "      IF (K .LT. 0) THEN", # 26
        "         MYFUNC = 0", # 27
        "      ELSE", # 28
        "         MYFUNC = K * 10", # 29
        "      END IF", # 30
        "      RETURN", # 31
        "      END FUNCTION MYFUNC", # 32
        "      SUBROUTINE ANOTHER_SUB", # 33
        "      REAL Y", # 34
        "      Y = 1.0", # 35
        "      DO WHILE (Y .LT. 10.0)", # 36
        "         Y = Y + 1.0", # 37
        "      END DO", # 38
        "      RETURN", # 39
        "      END" # 40
    ]

    analyzer = FortranAnalyzer()
    analysis_results = analyzer.analyze(fortran_code_example)
    analyzer.generate_nested_text_report("fortran_analysis_report.txt")

    print("\n--- Analysis Data (JSON format) ---")
    import json
    print(json.dumps(analysis_results, indent=2))