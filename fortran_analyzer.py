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
            # コメント行判定（original_contentで判定：1カラム目のみ）
            if len(original_line) > 0 and original_line[0] in ('c', 'C', '*', '!'):
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

    def _identify_statement_type(self, content):
        """文のタイプを識別する（強化版）"""
        content = content.strip().upper()
        # 宣言文の識別
        declaration_keywords = [
            'INTEGER', 'REAL', 'DOUBLE PRECISION', 'COMPLEX', 'LOGICAL', 
            'CHARACTER', 'DIMENSION', 'PARAMETER', 'COMMON', 'DATA'
        ]
        for keyword in declaration_keywords:
            if content.startswith(keyword):
                return 'DECLARATION'
        # INCLUDE文の識別
        if content.startswith('INCLUDE'):
            return 'INCLUDE'
        # IF/ELSE/ENDIF/DO/ENDDO
        if re.match(r'^IF\s*\(.*\)\s*THEN$', content, re.IGNORECASE):
            return 'IF_BLOCK_START'
        if re.match(r'^ELSE\s*IF\s*\(.*\)\s*THEN$', content, re.IGNORECASE):
            return 'ELSE_IF'
        if re.match(r'^ELSE$', content, re.IGNORECASE):
            return 'ELSE'
        if content in ['END IF', 'ENDIF']:
            return 'END_IF'
        if re.match(r'^DO(\s|$)', content, re.IGNORECASE):
            return 'DO_BLOCK_START'
        if content in ['END DO', 'ENDDO']:
            return 'DO_BLOCK_END'
        # CALL文
        if content.startswith('CALL '):
            return 'CALL'
        # IO文
        if content.startswith('WRITE') or content.startswith('READ') or content.startswith('PRINT'):
            return 'IO_OPERATION'
        # CONTINUE
        if content == 'CONTINUE':
            return 'CONTINUE'
        # GOTO
        if content.startswith('GOTO ') or content.startswith('GO TO '):
            return 'GOTO'
        # STOP
        if content == 'STOP':
            return 'STOP'
        # RETURN
        if content == 'RETURN':
            return 'RETURN'
        # 代入文
        if '=' in content and not content.startswith('IF'):
            return 'ASSIGNMENT_STATEMENT'
        return 'CODE_STATEMENT_RAW'

    def _identify_units_and_labels(self, logical_lines_data, all_code_lines_for_original_content):
        """
        プログラムユニットとラベルをシンプルなロジックで識別し、各ユニットのraw_statementsに文を追加する。
        命令行が現れた時点でNONAMEユニットを開始し、明示的なユニット宣言が現れたらその都度新しいユニットを開始・切り替え、ユニット終了キーワードで閉じる。
        INCLUDEや宣言文、コメント行のみの部分はユニットとして出力しない。
        """
        current_unit_data = None
        unit_opened = False
        for idx, line_data in enumerate(logical_lines_data):
            content = line_data['logical_content'].strip()
            original_content = line_data['original_content']
            # 空行の処理
            if not content:
                line_data['type'] = 'blank_line'
                if unit_opened and current_unit_data:
                    current_unit_data['raw_statements'].append(line_data)
                continue
            # コメント行の処理（original_contentで判定：1カラム目のみ）
            if len(original_content) > 0 and original_content[0] in ('c', 'C', '*', '!'):
                line_data['type'] = 'COMMENT'
                if current_unit_data:
                    current_unit_data['raw_statements'].append(line_data)
                continue
            # ラベルの抽出
            label = None
            if len(line_data['original_content']) >= 5 and line_data['original_content'][:5].strip().isdigit():
                label = line_data['original_content'][:5].strip()
                content = content[5:].strip() if len(content) > 5 else ''
            elif content[:5].strip().isdigit():
                label = content[:5].strip()
                content = content[5:].strip()
            line_data['label'] = label
            # 文のタイプを判定
            stmt_type = self._identify_statement_type(content)
            # IFブロックと論理IF文の厳密な判定
            if re.match(r'^IF\s*\(.*\)\s*THEN\s*$', content, re.IGNORECASE):
                stmt_type = 'IF_BLOCK_START'
            elif re.match(r'^IF\s*\(.*\)\)\s*[^T][^H][^E][^N].*$', content, re.IGNORECASE) or (content.upper().startswith('IF(') and not content.rstrip().upper().endswith('THEN')):
                stmt_type = 'LOGICAL_IF'
            # ラベル付きCONTINUEのtype判定を必ずCONTINUEに
            if label and content.upper() == 'CONTINUE':
                line_data['type'] = 'CONTINUE'
                line_data['logical_content'] = 'CONTINUE'
            elif (stmt_type == 'CONTINUE') and label:
                line_data['type'] = 'CONTINUE'
                line_data['logical_content'] = 'CONTINUE'
            else:
                line_data['type'] = stmt_type
            # DO文のラベル抽出（DO 10 K=1,N など）
            if stmt_type == 'DO_BLOCK_START':
                do_label_match = re.match(r'^\s*DO\s+(\d+)\b', line_data['original_content'], re.IGNORECASE)
                if not do_label_match:
                    label_match = re.match(r'^\s*(\d+)\s*DO', line_data['original_content'], re.IGNORECASE)
                    if label_match:
                        do_label = label_match.group(1)
                        line_data['label'] = do_label
                else:
                    do_label = do_label_match.group(1)
                    line_data['label'] = do_label
            # ユニット開始キーワード（PROGRAM/SUBROUTINE/FUNCTION/MODULE/BLOCK DATA）
            unit_declared = False
            for unit_type, pattern in self.unit_start_keywords.items():
                match = pattern.match(content)
                if match:
                    unit_name = match.group(1) if match.group(1) else f"NONAME_{unit_type.replace(' ', '_')}"
                    unit_args = match.group(2) if len(match.groups()) > 1 and match.group(2) else ""
                    # 既存ユニットを閉じる
                    if current_unit_data:
                        # 命令行が1つでも含まれているかチェック
                        has_code = any(
                            stmt['type'] not in ['DECLARATION', 'INCLUDE', 'COMMENT', 'comment_line', 'blank_line', 'BLANK', 'UNIT_DECLARATION_RAW', 'UNIT_END_RAW']
                            for stmt in current_unit_data['raw_statements']
                        )
                        if has_code:
                            self.analysis_data['units'].append(current_unit_data)
                    # 新ユニット開始
                    current_unit_data = {
                        'id': self.generate_id(),
                        'name': unit_name,
                        'type': unit_type.replace(' ', '_').upper(),
                        'start_line': line_data['physical_line_nums'][0],
                        'end_line': -1,
                        'args': unit_args,
                        'labels': {},
                        'raw_statements': []
                    }
                    current_unit_data['raw_statements'].append({
                        'physical_line_num': line_data['physical_line_nums'][0],
                        'logical_content': line_data['logical_content'],
                        'original_content': line_data['original_content'],
                        'label': label,
                        'type': 'UNIT_DECLARATION_RAW',
                        'unit_type': unit_type.replace(' ', '_').upper(),
                        'name': unit_name,
                        'args': unit_args
                    })
                    unit_opened = True
                    unit_declared = True
                    break
            if unit_declared:
                continue
            # ユニット終了キーワード
            if current_unit_data:
                for unit_type_end, pattern_end in self.unit_end_keywords.items():
                    match_end = pattern_end.match(content)
                    if match_end:
                        current_unit_data['end_line'] = line_data['physical_line_nums'][0]
                        current_unit_data['raw_statements'].append({
                            'physical_line_num': line_data['physical_line_nums'][0],
                            'logical_content': line_data['logical_content'],
                            'original_content': line_data['original_content'],
                            'type': 'UNIT_END_RAW',
                            'unit_type': unit_type_end.replace('END ', '').replace(' ', '_').upper()
                        })
                        # 命令行が1つでも含まれているかチェック
                        has_code = any(
                            stmt['type'] not in ['DECLARATION', 'INCLUDE', 'COMMENT', 'comment_line', 'blank_line', 'BLANK', 'UNIT_DECLARATION_RAW', 'UNIT_END_RAW']
                            for stmt in current_unit_data['raw_statements']
                        )
                        if has_code:
                            self.analysis_data['units'].append(current_unit_data)
                        current_unit_data = None
                        unit_opened = False
                        break
                if not unit_opened:
                    continue
            # 命令行またはINCLUDE文が現れたらNONAMEユニットを開始
            if not unit_opened and stmt_type not in ['DECLARATION', 'COMMENT', 'comment_line', 'blank_line', 'BLANK'] and content:
                current_unit_data = {
                    'id': self.generate_id(),
                    'name': 'NONAME',
                    'type': 'PROGRAM',
                    'start_line': line_data['physical_line_nums'][0],
                    'end_line': -1,
                    'args': '',
                    'labels': {},
                    'raw_statements': []
                }
                current_unit_data['raw_statements'].append({
                    'physical_line_num': line_data['physical_line_nums'][0],
                    'logical_content': '',
                    'original_content': '',
                    'label': None,
                    'type': 'UNIT_DECLARATION_RAW',
                    'unit_type': 'PROGRAM',
                    'name': 'NONAME',
                    'args': ''
                })
                unit_opened = True
            # ユニット内の文をraw_statementsに追加
            if unit_opened and current_unit_data:
                stmt = {
                    'physical_line_num': line_data['physical_line_nums'][0],
                    'logical_content': line_data['logical_content'],
                    'original_content': line_data['original_content'],
                    'label': line_data['label'],
                    'type': line_data['type']
                }
                current_unit_data['raw_statements'].append(stmt)
            # --- 固定形式・自由形式のラベル付きCONTINUE判定を厳密化 ---
            fixed_form_label_continue = (
                len(line_data['original_content']) >= 13 and
                line_data['original_content'][:5].strip().isdigit() and
                line_data['original_content'][5:].lstrip().upper().startswith('CONTINUE')
            )
            free_form_label_continue = re.match(r'^\s*(\d{1,5})\s+CONTINUE\b', line_data['original_content'], re.IGNORECASE)
            if fixed_form_label_continue or free_form_label_continue:
                if fixed_form_label_continue:
                    label = line_data['original_content'][:5].strip()
                else:
                    label = free_form_label_continue.group(1)
                line_data['label'] = label
                line_data['type'] = 'CONTINUE'
                line_data['logical_content'] = 'CONTINUE'
                if unit_opened and current_unit_data:
                    current_unit_data['raw_statements'].append(line_data)
                # ここでcontinueし、以降の通常文追加処理を完全にスキップ
                continue
        # ファイル末尾でユニットが開いていた場合、命令行が1つでも含まれていればappend
        if current_unit_data:
            has_code = any(
                stmt['type'] not in ['DECLARATION', 'INCLUDE', 'COMMENT', 'comment_line', 'blank_line', 'BLANK', 'UNIT_DECLARATION_RAW', 'UNIT_END_RAW']
                for stmt in current_unit_data['raw_statements']
            )
            if has_code:
                self.analysis_data['units'].append(current_unit_data)

    def _analyze_unit_structures(self):
        """
        各プログラムユニット内の文のインデントレベルを解析する。
        DO文のラベルとCONTINUE文のラベルを厳密に対応させる（ラベルごとの多重度管理）。
        """
        for unit_data in self.analysis_data['units']:
            structure_stack = []  # ネストされた制御構造を管理
            do_label_count = {}   # DOラベルの多重度を管理
            stmts = unit_data['statements'] if 'statements' in unit_data else unit_data['raw_statements']
            for stmt in stmts:
                # コメントと空行はスキップ
                if stmt['type'] in ['comment_line', 'COMMENT', 'blank_line', 'BLANK']:
                    continue
                # IF/ELSE/ENDIF
                if stmt['type'] == 'IF_BLOCK_START':
                    stmt['indent_level'] = len(structure_stack)
                    structure_stack.append('IF')
                elif stmt['type'] == 'ELSE_IF':
                    stmt['indent_level'] = len(structure_stack) - 1 if structure_stack else 0
                elif stmt['type'] == 'ELSE':
                    stmt['indent_level'] = len(structure_stack) - 1 if structure_stack else 0
                elif stmt['type'] == 'END_IF':
                    stmt['indent_level'] = len(structure_stack) - 1 if structure_stack else 0
                    if structure_stack and structure_stack[-1] == 'IF':
                        structure_stack.pop()
                # DO/CONTINUEの多重ラベル対応
                elif stmt['type'] == 'DO_BLOCK_START':
                    stmt['indent_level'] = len(structure_stack)
                    label = stmt.get('label')
                    if label:
                        do_label_count[label] = do_label_count.get(label, 0) + 1
                        structure_stack.append(('DO', label))
                    else:
                        structure_stack.append(('DO', None))
                elif stmt['type'] == 'DO_BLOCK_END':
                    stmt['indent_level'] = len(structure_stack) - 1 if structure_stack else 0
                    # ラベルなしDOのpop
                    for i in range(len(structure_stack)-1, -1, -1):
                        if structure_stack[i][0] == 'DO':
                            structure_stack.pop(i)
                            break
                elif stmt['type'] == 'CONTINUE' and stmt.get('label'):
                    label = stmt['label']
                    count = do_label_count.get(label, 0)
                    stmt['indent_level'] = len(structure_stack) - count if count > 0 else len(structure_stack)
                    # count回pop
                    for _ in range(count):
                        # DOラベルが一致するものだけpop
                        for i in range(len(structure_stack)-1, -1, -1):
                            if structure_stack[i] == ('DO', label):
                                structure_stack.pop(i)
                                break
                    do_label_count[label] = 0  # 使い切ったら0に
                elif stmt['type'] == 'CONTINUE':
                    # ラベルなしCONTINUEは現在のネストレベルを使用
                    stmt['indent_level'] = len(structure_stack)
                elif stmt['type'] == 'END':
                    stmt['indent_level'] = 0
                    structure_stack.clear()
                    do_label_count.clear()
                elif stmt['type'] == 'LOGICAL_IF':
                    stmt['indent_level'] = len(structure_stack)
                else:
                    stmt['indent_level'] = len(structure_stack)
            structure_stack.clear()
            do_label_count.clear()

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
        空行（type: 'blank_line' または 'BLANK'）は出力しない。
        CONTINUE文がある物理行番号ではCONTINUEのみ出力し、それ以外の行は全ての有効な文を出力する。
        physical_line_numsは常にリスト形式で出力し、logical_contentの前に配置する。
        continuation_typeがnullの場合は出力しない。
        """
        export_data = {'units': []}
        for unit in self.analysis_data['units']:
            unit_copy = dict(unit)
            unit_copy.pop('structures', None)
            # --- CONTINUE優先の重複排除用: 物理行番号ごとにCONTINUEがあればCONTINUEのみ出力 ---
            stmts_by_line = {}
            if 'raw_statements' in unit_copy:
                for stmt in unit_copy['raw_statements']:
                    # 空行は除外
                    if stmt.get('type') in ['blank_line', 'BLANK']:
                        continue
                    # physical_line_num/physical_line_numsの取得
                    if 'physical_line_nums' in stmt:
                        nums = tuple(stmt['physical_line_nums'])
                    elif 'physical_line_num' in stmt:
                        nums = (stmt['physical_line_num'],)
                    else:
                        nums = ()
                    if not nums:
                        continue
                    # 物理行番号ごとにリスト化
                    if nums not in stmts_by_line:
                        stmts_by_line[nums] = []
                    stmts_by_line[nums].append(stmt)
                # 出力用リスト
                filtered_statements = []
                for nums, stmts in stmts_by_line.items():
                    # CONTINUE文があればそれだけ出力、なければ全て出力
                    continue_stmts = [s for s in stmts if s.get('type') == 'CONTINUE']
                    if continue_stmts:
                        stmts_to_output = continue_stmts
                    else:
                        stmts_to_output = stmts
                    for stmt in stmts_to_output:
                        out_stmt = dict(stmt)
                        # continuation_typeがNoneの場合は出力しない
                        if 'continuation_type' in out_stmt and out_stmt['continuation_type'] is None:
                            out_stmt.pop('continuation_type')
                        # physical_line_num（単一値）は出力しない
                        if 'physical_line_num' in out_stmt:
                            out_stmt.pop('physical_line_num')
                        # physical_line_numsを常にリスト形式でlogical_contentの前に配置
                        out_stmt['physical_line_nums'] = list(nums)
                        # logical_contentの前にphysical_line_numsを移動
                        if 'logical_content' in out_stmt:
                            new_stmt = {}
                            new_stmt['physical_line_nums'] = out_stmt.pop('physical_line_nums')
                            for k, v in out_stmt.items():
                                new_stmt[k] = v
                            filtered_statements.append(new_stmt)
                        else:
                            filtered_statements.append(out_stmt)
                unit_copy['statements'] = filtered_statements
                unit_copy.pop('raw_statements', None)
            elif 'statements' not in unit_copy:
                unit_copy['statements'] = []
            export_data['units'].append(unit_copy)
        with open(output_filepath, 'w', encoding='utf-8') as f:
            json.dump(export_data, f, ensure_ascii=False, indent=2)

    def generate_nested_text_report(self, output_filepath):
        """
        ネストレベル付きのテキストレポートを生成する。
        """
        try:
            # _generate_flow_reportを使用してレポートを生成
            self._generate_flow_report(output_filepath)
            self.logger.info(f"ネストレベル付きレポートが '{output_filepath}' に生成されました。")
        except Exception as e:
            self.logger.error(f"レポート生成中にエラーが発生しました: {e}")

    def _generate_flow_report(self, output_filepath):
        """フローレポートを生成する"""
        with open(output_filepath, 'w', encoding='utf-8') as f:
            for unit in self.analysis_data['units']:
                # ユニット名を出力
                if unit.get('name'):
                    f.write(f"\n=== {unit['type']}: {unit['name']} ===\n")
                else:
                    f.write(f"\n=== {unit['type']} ===\n")

                for stmt in unit['raw_statements']:
                    # コメントと空行はスキップ
                    if stmt['type'] in ['comment_line', 'COMMENT', 'blank_line', 'BLANK']:
                        continue
                    # physical_line_numが無い場合はスキップ
                    if 'physical_line_num' not in stmt:
                        continue
                    # インデントを計算
                    indent = '    ' * stmt['indent_level']
                    # 行番号の処理
                    line_prefix = f"L{stmt['physical_line_num']}: "
                    # ラベル付きCONTINUE文の特別処理
                    if stmt['type'] == 'CONTINUE' and stmt.get('label'):
                        f.write(f"{indent}{line_prefix}{stmt['label']} CONTINUE\n")
                        continue
                    # その他の文の処理
                    content = stmt['logical_content']
                    if stmt.get('label') and stmt['type'] != 'CONTINUE':
                        content = f"{stmt['label']}: {content}"
                    f.write(f"{indent}{line_prefix}{content}\n")

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