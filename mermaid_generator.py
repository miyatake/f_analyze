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
        """
        print("\nMermaidフローチャート生成を開始します")
        base_name = os.path.splitext(os.path.basename(source_filename))[0]

        if 'units' not in self.analysis_data:
            logging.warning("解析データにプログラムユニット情報がありません。")
            return

        for i, unit_data in enumerate(self.analysis_data['units'], 1):
            unit_name = unit_data['name']
            print(f"ユニット {i}/{len(self.analysis_data['units'])} ({unit_name}) のチャートを生成中...")
            
            # フローチャートに関わる構造のみをフィルタリング
            visible_structs = [s for s in unit_data['structures'] if s['type'] in 
                               ('IF_BLOCK_START', 'ELSE', 'ELSE_IF', 'END_IF', 'CALL', 'STOP', 'END')]
            
            if not visible_structs:
                logging.info(f"ユニット '{unit_name}' には描画対象の構造がありません。")
                continue

            node_defs = self._generate_node_definitions(unit_data, visible_structs)
            edge_defs = self._generate_edge_definitions(unit_data, visible_structs)

            self._generate_mermaid_file(base_name, i, unit_data, node_defs, edge_defs)
  
    def _generate_node_ids(self, unit_data):
        """
        フェーズ1: すべてのノードIDを生成します。
        """
        node_id_map = {}  # {line_num: node_id}
        sorted_structures = unit_data['sorted_structures']

        # 一度のループで全てのノードIDを生成
        for struct in sorted_structures:
            if struct['type'] == 'LABEL':
                node_id_map[struct['line']] = f"n_L{struct['line']}"
            elif struct['type'] == 'INCLUDE':
                if struct['line'] not in node_id_map:  # 連続INCLUDEの最初の行のみ処理
                    node_id_map[struct['line']] = f"n_L{struct['line']}"
            elif struct['type'] == 'LOGICAL_IF':
                node_id_map[struct['line']] = f"n_L{struct['line']}_cond"
                node_id_map[f"{struct['line']}_stmt"] = f"n_L{struct['line']}_stmt"
            elif struct['type'] not in ['END_IF', 'END_DO', 'CONTINUE_END_DO', 'END_SELECT']:
                node_id_map[struct['line']] = f"n_L{struct['line']}"

        return node_id_map


    def _generate_node_definitions(self, unit_data, visible_structs):
        """ノード定義を生成します。"""
        node_defs = [f'    start_{unit_data["name"]}(["Start: {unit_data["name"]}"])']
        
        for s in visible_structs:
            line, type = s['line'], s['type']
            node_id = f"L{line}"
            
            if type == 'IF_BLOCK_START':
                node_defs.append(f'    {node_id}{{"L{line}: IF ({s["condition"]})"}}')
            elif type == 'CALL':
                node_defs.append(f'    {node_id}[["L{line}: CALL {s["target"]}"]]')
            elif type == 'ELSE':
                node_defs.append(f'    {node_id}["L{line}: ELSE"]')
            elif type == 'ELSE_IF':
                 node_defs.append(f'    {node_id}{{"L{line}: ELSE IF ({s["condition"]})"}}')
            elif type == 'END_IF':
                node_defs.append(f'    {node_id}("L{line}: END IF")')
            elif type == 'STOP':
                node_defs.append(f'    {node_id}(["L{line}: STOP"])')
            elif type == 'END':
                node_defs.append(f'    {node_id}(["L{line}: END"])')

        return node_defs

    def _generate_edge_definitions(self, unit_data, visible_structs):
        """エッジ定義（接続）を生成します。"""
        edges = set()
        struct_map = {s['line']: s for s in visible_structs}
        line_to_idx = {s['line']: i for i, s in enumerate(visible_structs)}

        def find_next_struct_idx(start_idx):
            return start_idx + 1 if start_idx + 1 < len(visible_structs) else None
            
        # Startノードから最初の構造へ
        if visible_structs:
            first_node_id = f"L{visible_structs[0]['line']}"
            edges.add(f'    start_{unit_data["name"]} --> {first_node_id}')

        for i, s in enumerate(visible_structs):
            node_id = f"L{s['line']}"

            # 接続先を決定
            # 修正点: 終端ノードの条件から 'STOP' を削除。'END' のみ終端とする。
            if s['type'] == 'END':
                continue # 終端ノードからは接続しない

            if s['type'] == 'IF_BLOCK_START':
                # TRUEパスへの接続
                true_target_idx = find_next_struct_idx(i)
                if true_target_idx is not None:
                    next_s = visible_structs[true_target_idx]
                    # IFの次がELSE/ENDIFでなければ、それがTRUEパスの行き先
                    if next_s['line'] != s.get('else_line') and next_s['line'] != s.get('end_if_line'):
                        edges.add(f"    {node_id} -->|TRUE| L{next_s['line']}")

                # FALSEパスへの接続
                if s.get('else_line'):
                    edges.add(f"    {node_id} -->|FALSE| L{s['else_line']}")
                elif s.get('end_if_line'):
                    edges.add(f"    {node_id} -->|FALSE| L{s['end_if_line']}")

            elif s['type'] == 'END_IF':
                # END_IFの次は、次の構造
                next_idx = find_next_struct_idx(i)
                if next_idx is not None:
                    edges.add(f"    {node_id} --> L{visible_structs[next_idx]['line']}")
            
            else: # 通常のノード (CALL, ELSE, ELSE_IF, STOP)
                # 次の構造を特定
                next_idx = find_next_struct_idx(i)
                if next_idx is None: continue
                
                next_s = visible_structs[next_idx]
                target_node_id = f"L{next_s['line']}"
                
                # 今のノードがIFブロックの最後のノードか判定
                is_last_in_true_block = next_s['type'] in ('ELSE', 'ELSE_IF')
                is_last_in_any_block = next_s['type'] == 'END_IF'

                if is_last_in_any_block or is_last_in_true_block:
                    # このノードはIF/ELSEブロックの最後なので、対応するEND_IFに飛ぶ
                    # どのIFに対応するかを遡って探す
                    for if_s in reversed(unit_data['structures']):
                        if if_s['type'] == 'IF_BLOCK_START' and if_s['line'] < s['line']:
                            if if_s.get('end_if_line') == next_s['line'] or \
                               (if_s.get('else_line') == next_s['line'] and if_s.get('end_if_line')):
                                target_node_id = f"L{if_s['end_if_line']}"
                                break
                
                edges.add(f"    {node_id} --> {target_node_id}")

        return sorted(list(edges))

    def _generate_mermaid_file(self, base_name, unit_index, unit_data, node_defs, edge_defs):
        """Mermaidファイルを生成します。"""
        if not node_defs and not edge_defs:
            print(f"ユニット {unit_data['name']} は空のチャートなのでスキップします。")
            return

        mermaid_content = ["flowchart TD"]
        mermaid_content.extend(node_defs)
        mermaid_content.extend(edge_defs)

        safe_unit_name = re.sub(r'[\\/:*?"<>|]', '_', unit_data['name'])
        output_filename = os.path.join(self.output_dir, f"{base_name}_{unit_index:02d}_{unit_data['type']}_{safe_unit_name}.mmd")

        try:
            with open(output_filename, 'w', encoding='utf-8') as f:
                f.write("\n".join(mermaid_content))
            print(f"Mermaidファイルを生成しました: {output_filename}")
        except Exception as e:
            logging.error(f"Mermaidファイルの保存中にエラーが発生しました: {e}")