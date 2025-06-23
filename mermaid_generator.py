import re
import os
import logging

class MermaidGenerator:
    def __init__(self, analysis_data, output_dir):
        self.analysis_data = analysis_data
        self.output_dir = output_dir
        if not os.path.exists(self.output_dir):
            os.makedirs(self.output_dir)

    def generate_flowcharts(self, source_filename):
        """
        解析データから各プログラムユニットのMermaidフローチャートを生成し、ファイルに保存します。
        このメソッドは、FortranAnalyzerによって既にフィルタリングされたデータを受け取ります。
        """
        logging.info("Mermaidフローチャート生成を開始します")
        base_name = os.path.splitext(os.path.basename(source_filename))[0]

        if 'units' not in self.analysis_data:
            logging.warning("解析データにプログラムユニット情報がありません。")
            return

        for i, unit_data in enumerate(self.analysis_data['units'], 1):
            unit_name = unit_data['name']
            logging.info(f"ユニット {i}/{len(self.analysis_data['units'])} ({unit_name}) のチャートを生成中...")
            
            # ここではFortranAnalyzerでフィルタリング済みの structures をそのまま使用
            # visible_structs は、既にフローチャートに関連する構造のみになっているはず
            visible_structs = unit_data['structures']
            
            # ソートして行順にする (FortranAnalyzer側でソート済みだが念のため)
            visible_structs.sort(key=lambda x: x['line'])

            if not visible_structs:
                logging.info(f"ユニット '{unit_name}' には描画対象の制御フロー構造がありません。")
                continue

            node_defs, node_id_map = self._generate_node_definitions(unit_data, visible_structs)
            edge_defs = self._generate_edge_definitions(unit_data, visible_structs, node_id_map)

            self._generate_mermaid_file(base_name, i, unit_data, node_defs, edge_defs)
  
    def _generate_node_definitions(self, unit_data, visible_structs):
        """ノード定義を生成します。"""
        node_defs = []
        node_id_map = {} # {line_num: node_id}

        # 開始ノード
        start_node_id = f"start_{unit_data['name'].replace('.', '_')}"
        node_defs.append(f'    {start_node_id}(["Start: {unit_data["name"]}"])')

        # 各構造のノードを定義
        for s in visible_structs:
            line = s['line']
            # 同じ行に複数の構造がある場合のノードIDの衝突を避けるために、タイプも含める
            node_id_prefix = f"L{line}"

            # インラインコメントを除去し、引用符をエスケープ
            # FortranAnalyzer側でコメント除去済みだが、Mermaidのエスケープ処理を適用
            content_display = s['content'].strip() # contentはすでにコメント除去済み
            content_display = content_display.replace('"', '#quot;') # Mermaid特殊文字のエスケープ

            if s['type'] == 'LABEL':
                node_id = f"{node_id_prefix}_label_{s['label']}"
                node_id_map[line] = node_id # ラベル行の参照はこれで
                node_defs.append(f'    {node_id}[/"L{line}: {content_display}"/]') # ラベルは台形
            else:
                node_id = f"{node_id_prefix}_{s['type'].lower()}" 
                node_id_map[line] = node_id # 汎用的な行番号参照のためのマップに追加

                if s['type'] == 'IF_BLOCK_START':
                    node_defs.append(f'    {node_id}{{"L{line}: IF ({s["condition"]})"}}')
                elif s['type'] == 'DO_BLOCK_START':
                    node_defs.append(f'    {node_id}[["L{line}: {content_display}"]]')
                elif s['type'] == 'CALL':
                    node_defs.append(f'    {node_id}[["L{line}: {content_display}"]]')
                elif s['type'] == 'ELSE':
                    node_defs.append(f'    {node_id}["L{line}: ELSE"]')
                elif s['type'] == 'ELSE_IF':
                    condition_text = s.get('condition', 'N/A')
                    node_defs.append(f'    {node_id}{{"L{line}: ELSE IF ({condition_text})"}}')
                elif s['type'] == 'END_IF':
                    node_defs.append(f'    {node_id}("L{line}: END IF")')
                elif s['type'] == 'END_DO':
                    node_defs.append(f'    {node_id}("L{line}: END DO")')
                elif s['type'] == 'CONTINUE_END_DO':
                    node_defs.append(f'    {node_id}("L{line}: {content_display}")')
                elif s['type'] == 'STOP':
                    node_defs.append(f'    {node_id}(["L{line}: STOP"])')
                elif s['type'] == 'END':
                    node_defs.append(f'    {node_id}(["L{line}: END"])')
                elif s['type'] == 'GOTO':
                    node_defs.append(f'    {node_id}[/"L{line}: GOTO {s["target_label"]}"/]')
                elif s['type'] == 'LOGICAL_IF':
                    node_defs.append(f'    {node_id}{{"L{line}: IF ({s["condition"]}) {s["statement"]}"}}')
                elif s['type'] == 'OTHER_STATEMENT': 
                     node_defs.append(f'    {node_id}[["L{line}: {content_display}"]]')
                elif s['type'] == 'END_UNIT_STRICT': # END PROGRAM/SUBROUTINE など
                     node_defs.append(f'    {node_id}(["L{line}: {content_display}"])')


        return node_defs, node_id_map

    def _generate_edge_definitions(self, unit_data, visible_structs, node_id_map):
        """エッジ定義（接続）を生成します。"""
        edges = set()
        
        # 実行可能構造のみを抽出（Mermaidノードとして定義されているもの）
        # _generate_node_definitionsでノードIDが作成されたものだけを対象にする
        executable_structures = [s for s in unit_data['structures'] if node_id_map.get(s['line'])]
        executable_structures.sort(key=lambda x: x['line']) # 念のためソート

        # 開始ノードから最初の実行可能な構造へ接続
        if executable_structures:
            start_node_id = f"start_{unit_data['name'].replace('.', '_')}"
            
            # ユニット内で最初の"実行可能な"ノードを探す
            actual_first_flow_node_id = None
            for s in executable_structures:
                # LABELはGOTOのターゲットになるが、それ自体はフローの開始点とはしない
                # OTHER_STATEMENTも基本的にはフローの開始点とはしないが、L64のような場合は含める
                # ユニット開始直後の `PROGRAM` や `SUBROUTINE_DECL` はスキップ
                if s['type'] not in ['LABEL', 'PROGRAM', 'SUBROUTINE_DECL', 'FUNCTION_DECL', 'INCLUDE']:
                    actual_first_flow_node_id = node_id_map.get(s['line'])
                    if actual_first_flow_node_id:
                        break
            
            if actual_first_flow_node_id:
                edges.add(f'    {start_node_id} --> {actual_first_flow_node_id}')


        for i, s in enumerate(executable_structures):
            line = s['line']
            s_type = s['type']
            current_node_id = node_id_map.get(line)
            
            if not current_node_id: continue # ノードIDがない場合はスキップ

            # 終端ノードからは接続しない
            if s_type in ['STOP', 'RETURN', 'END', 'END_UNIT_STRICT']:
                continue

            # 次の「フロー制御に関わる」実行可能ノードを探す
            # LABEL, INCLUDE, UNIT_DECL はフロー制御ノードではないためスキップ
            next_executable_node_id = None
            for j in range(i + 1, len(executable_structures)):
                potential_next_s = executable_structures[j]
                if potential_next_s['type'] not in ['LABEL', 'INCLUDE', 'PROGRAM', 'SUBROUTINE_DECL', 'FUNCTION_DECL', 'END_UNIT_STRICT']:
                    next_executable_node_id = node_id_map.get(potential_next_s['line'])
                    if next_executable_node_id: # 有効なノードIDがあれば
                        break
            
            # IF/ELSE/ENDIFの処理
            if s_type == 'IF_BLOCK_START':
                # TRUEパス: 直後の実行可能ステートメント
                if next_executable_node_id:
                    edges.add(f'    {current_node_id} -->|TRUE| {next_executable_node_id}')
                
                # FALSEパス: ELSE/ELSE_IFがあればそこへ、なければEND_IFへ
                false_target_line = None
                for k in range(unit_data['structures'].index(s) + 1, len(unit_data['structures'])):
                    check_s = unit_data['structures'][k]
                    # IFブロックのネストレベルを考慮してEND_IFを探す
                    if check_s['type'] in ['ELSE', 'ELSE_IF'] and check_s['nest_level'] == s['nest_level']:
                        false_target_line = check_s['line']
                        break
                    elif check_s['type'] == 'END_IF' and check_s['nest_level'] == s['nest_level']:
                        false_target_line = check_s['line']
                        break
                
                if false_target_line and node_id_map.get(false_target_line):
                    edges.add(f'    {current_node_id} -->|FALSE| {node_id_map[false_target_line]}')

            elif s_type in ['ELSE', 'ELSE_IF']:
                # 各ELSE/ELSE_IFブロックは、対応するEND_IFに接続
                end_if_target_line = None
                # 現在のELSE/ELSE_IFと同じネストレベルのEND_IFを探す
                for k in range(unit_data['structures'].index(s) + 1, len(unit_data['structures'])):
                    check_s = unit_data['structures'][k]
                    if check_s['type'] == 'END_IF' and check_s['nest_level'] == s['nest_level']:
                        end_if_target_line = check_s['line']
                        break
                
                if end_if_target_line and node_id_map.get(end_if_target_line):
                    edges.add(f'    {current_node_id} --> {node_id_map[end_if_target_line]}')

                # ELSE/ELSE_IFの後の通常のフロー（OTHER_STATEMENTを含む）
                if next_executable_node_id:
                    edges.add(f'    {current_node_id} --> {next_executable_node_id}')

            elif s_type == 'END_IF':
                # END_IFの次の実行可能ステートメントへ接続
                if next_executable_node_id:
                    edges.add(f'    {current_node_id} --> {next_executable_node_id}')

            # DO/END DO/CONTINUE_END_DOの処理
            elif s_type == 'DO_BLOCK_START':
                # DOの次への通常フロー (ループ本体の開始)
                if next_executable_node_id:
                    edges.add(f'    {current_node_id} --> {next_executable_node_id}')
            
            elif s_type == 'END_DO' or s_type == 'CONTINUE_END_DO':
                # ループの繰り返しパス (END DO/CONTINUE から対応する DO_BLOCK_START へ)
                matching_do_line = None
                for k in range(unit_data['structures'].index(s) - 1, -1, -1):
                    prev_s = unit_data['structures'][k]
                    if prev_s['type'] == 'DO_BLOCK_START' and prev_s['nest_level'] == s['nest_level']: 
                        matching_do_line = prev_s['line']
                        break
                
                if matching_do_line and node_id_map.get(matching_do_line):
                    edges.add(f'    {current_node_id} --> {node_id_map[matching_do_line]}')
                
                # ループ終了後のパス (END DO/CONTINUE から次の実行可能ステートメントへ)
                if next_executable_node_id:
                    edges.add(f'    {current_node_id} --> {next_executable_node_id}')

            elif s_type == 'LOGICAL_IF':
                # 論理IFの次への通常フロー
                if next_executable_node_id:
                    edges.add(f'    {current_node_id} --> {next_executable_node_id}')
            
            elif s_type == 'CALL':
                # CALLの次への通常フロー
                if next_executable_node_id:
                    edges.add(f'    {current_node_id} --> {next_executable_node_id}')
            
            elif s_type == 'GOTO':
                # GOTOのターゲットへ接続 (GOTOの後のシーケンシャルフローはない)
                target_label_line = None
                for target_s in unit_data['structures']:
                    if target_s['type'] == 'LABEL' and target_s['label'] == s['target_label']:
                        target_label_line = target_s['line']
                        break
                if target_label_line and node_id_map.get(target_label_line):
                    edges.add(f'    {current_node_id} --> {node_id_map[target_label_line]}')
            
            elif s_type == 'OTHER_STATEMENT': # WRITE文などのOTHER_STATEMENT
                # OTHER_STATEMENTの次への通常フロー
                if next_executable_node_id:
                    edges.add(f'    {current_node_id} --> {next_executable_node_id}')

            elif s_type == 'LABEL':
                # LABELの次の実行可能ノードへ接続
                if next_executable_node_id:
                    edges.add(f'    {current_node_id} --> {next_executable_node_id}')
            
            # Unit終端処理: END, STOP, RETURN から明示的なENDノードへ (または終端自体)
            # L73_stop --> L74_end の接続
            elif s_type in ['STOP', 'RETURN']:
                final_end_node_id = None
                for final_s in unit_data['structures']:
                    if final_s['type'] == 'END' and final_s['line'] == unit_data['end_line']:
                        final_end_node_id = node_id_map.get(final_s['line'])
                        break
                if final_end_node_id:
                    edges.add(f'    {current_node_id} --> {final_end_node_id}')

            elif s_type == 'END':
                pass # END文自体がフローの終端

        return sorted(list(edges))

    def _generate_mermaid_file(self, base_name, unit_index, unit_data, node_defs, edge_defs):
        """Mermaidファイルを生成します。"""
        mermaid_content = ["flowchart TD"]

        mermaid_content.extend(node_defs)
        mermaid_content.extend(edge_defs)

        safe_unit_name = re.sub(r'[\\/:*?"<>|]', '_', unit_data['name'])
        output_filename = os.path.join(self.output_dir, f"{base_name}_{unit_index:02d}_{unit_data['type']}_{safe_unit_name}.mmd")

        try:
            with open(output_filename, 'w', encoding='utf-8') as f:
                f.write("\n".join(mermaid_content))
            logging.info(f"Mermaidファイルを生成しました: {output_filename}")
        except Exception as e:
            logging.error(f"Mermaidファイルの保存中にエラーが発生しました: {e}")
