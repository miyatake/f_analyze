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
            print("解析データにプログラムユニット情報がありません。Mermaidチャートを生成できません。")
            return

        # 構造体を事前にソートして再利用
        for unit_data in self.analysis_data['units']:
            unit_data['sorted_structures'] = sorted(unit_data['structures'], key=lambda x: x['line'])

        for i, unit_data in enumerate(self.analysis_data['units'], 1):
            print(f"ユニット {i}/{len(self.analysis_data['units'])} の処理を開始: {unit_data['name']}")
            
            # フェーズ1: ノードIDの生成
            node_id_map = self._generate_node_ids(unit_data)
            if not node_id_map:
                continue

            # フェーズ2: ノード定義の生成
            node_defs = self._generate_node_definitions(unit_data, node_id_map)
            if not node_defs:
                continue

            # フェーズ3: エッジ定義の生成
            edge_defs = self._generate_edge_definitions(unit_data, node_id_map)
            if not edge_defs:
                continue

            # フェーズ4: Mermaidファイルの生成
            self._generate_mermaid_file(base_name, i, unit_data, node_defs, edge_defs)
            print(f"ユニット {i}/{len(self.analysis_data['units'])} の処理が完了: {unit_data['name']}")

    def _generate_node_ids(self, unit_data):
        """
        フェーズ1: すべてのノードIDを生成します。
        """
        node_id_map = {}  # {line_num: node_id}
        node_counter = 0
        sorted_structures = unit_data['sorted_structures']

        # 一度のループで全てのノードIDを生成
        for struct in sorted_structures:
            if struct['type'] == 'LABEL':
                node_counter += 1
                node_id_map[struct['line']] = f"n{node_counter}"
            elif struct['type'] == 'INCLUDE':
                if struct['line'] not in node_id_map:  # 連続INCLUDEの最初の行のみ処理
                    node_counter += 1
                    node_id_map[struct['line']] = f"n{node_counter}"
            elif struct['type'] == 'LOGICAL_IF':
                node_counter += 1
                node_id_map[struct['line']] = f"n{node_counter}_cond"
                node_counter += 1
                node_id_map[f"{struct['line']}_stmt"] = f"n{node_counter}_stmt"
            elif struct['type'] not in ['END_IF', 'END_DO', 'CONTINUE_END_DO', 'END_SELECT']:
                node_counter += 1
                node_id_map[struct['line']] = f"n{node_counter}"

        return node_id_map

    def _generate_node_definitions(self, unit_data, node_id_map):
        """
        フェーズ2: ノード定義を生成します。
        """
        node_defs = []
        start_node_id = f"U1_{unit_data['name']}_start"
        node_defs.append(f'    {start_node_id}(["Start: {unit_data["name"]}"])')

        sorted_structures = unit_data['sorted_structures']
        consecutive_includes = []
        current_include_line = None

        for struct in sorted_structures:
            if struct['type'] == 'INCLUDE':
                if not current_include_line:
                    current_include_line = struct['line']
                    consecutive_includes.append(struct['target'])
            else:
                if consecutive_includes:
                    node_id = node_id_map.get(current_include_line)
                    if node_id:
                        label_content = "<br>".join([f"'{inc}'" for inc in consecutive_includes])
                        node_defs.append(f'    {node_id}[("INCLUDE:<br>{label_content}")]')
                        consecutive_includes = [] 
                    current_include_line = None

                if struct['type'] == 'CALL':
                    node_id = node_id_map.get(struct['line'])
                    if node_id:
                        node_defs.append(f'    {node_id}[["L{struct["line"]}: CALL {struct["target"]}"]]')
                elif struct['type'] == 'IF_BLOCK_START':
                    node_id = node_id_map.get(struct['line'])
                    if node_id:
                        node_defs.append(f'    {node_id}{{"L{struct["line"]}: IF ({struct["condition"]})" }}')
                elif struct['type'] == 'LOGICAL_IF':
                    cond_node_id = node_id_map.get(f"{struct['line']}_cond")
                    stmt_node_id = node_id_map.get(f"{struct['line']}_stmt")
                    if cond_node_id and stmt_node_id:
                        node_defs.append(f'    {cond_node_id}{{"L{struct["line"]}: IF ({struct["condition"]})" }}')
                        node_defs.append(f'    {stmt_node_id}["{struct["statement"]}"]')
                elif struct['type'] == 'ELSE':
                    node_id = node_id_map.get(struct['line'])
                    if node_id:
                        node_defs.append(f'    {node_id}["L{struct["line"]}: ELSE"]')
                elif struct['type'] == 'STOP':
                    node_id = node_id_map.get(struct['line'])
                    if node_id:
                        node_defs.append(f'    {node_id}([L{struct["line"]}: STOP])')
                elif struct['type'] == 'RETURN':
                    node_id = node_id_map.get(struct['line'])
                    if node_id:
                        node_defs.append(f'    {node_id}([L{struct["line"]}: RETURN])')

        return node_defs

    def _generate_edge_definitions(self, unit_data, node_id_map):
        """
        フェーズ3: エッジ定義を生成します。
        """
        edge_defs = []
        current_node_id = f"U1_{unit_data['name']}_start"
        if_stack = []
        do_stack = []
        select_case_stack = []

        sorted_structures = unit_data['sorted_structures']
        edge_set = set()  # 重複エッジを防ぐためのセット

        for j, struct in enumerate(sorted_structures):
            if struct['type'] == 'INCLUDE':
                node_id = node_id_map.get(struct['line'])
                if node_id and f"{current_node_id} --> {node_id}" not in edge_set:
                    edge_defs.append(f"    {current_node_id} --> {node_id}")
                    edge_set.add(f"{current_node_id} --> {node_id}")
                    current_node_id = node_id 
            elif struct['type'] == 'CALL':
                node_id = node_id_map.get(struct['line'])
                if node_id and f"{current_node_id} --> {node_id}" not in edge_set:
                    edge_defs.append(f"    {current_node_id} --> {node_id}")
                    edge_set.add(f"{current_node_id} --> {node_id}")
                    current_node_id = node_id
            elif struct['type'] == 'IF_BLOCK_START':
                node_id = node_id_map.get(struct['line'])
                if node_id:
                    if f"{current_node_id} --> {node_id}" not in edge_set:
                        edge_defs.append(f"    {current_node_id} --> {node_id}")
                        edge_set.add(f"{current_node_id} --> {node_id}")
                    if_stack.append({
                        'if_node_id': node_id,
                        'path_end_nodes': [], 
                        'else_path_started': False,
                        'true_next_node': None
                    })
                    current_node_id = node_id 
            elif struct['type'] == 'LOGICAL_IF':
                cond_node_id = node_id_map.get(f"{struct['line']}_cond")
                stmt_node_id = node_id_map.get(f"{struct['line']}_stmt")
                if cond_node_id and stmt_node_id:
                    if f"{current_node_id} --> {cond_node_id}" not in edge_set:
                        edge_defs.append(f"    {current_node_id} --> {cond_node_id}")
                        edge_set.add(f"{current_node_id} --> {cond_node_id}")
                    if f"{cond_node_id} -->|TRUE| {stmt_node_id}" not in edge_set:
                        edge_defs.append(f"    {cond_node_id} -->|TRUE| {stmt_node_id}")
                        edge_set.add(f"{cond_node_id} -->|TRUE| {stmt_node_id}")
                    current_node_id = stmt_node_id
            elif struct['type'] == 'ELSE':
                if if_stack:
                    prev_if_info = if_stack[-1]
                    node_id = node_id_map.get(struct['line'])
                    if node_id and f"{prev_if_info['if_node_id']} -->|FALSE| {node_id}" not in edge_set:
                        edge_defs.append(f"    {prev_if_info['if_node_id']} -->|FALSE| {node_id}")
                        edge_set.add(f"{prev_if_info['if_node_id']} -->|FALSE| {node_id}")
                        current_node_id = node_id
            elif struct['type'] == 'END_IF':
                if if_stack:
                    prev_if_info = if_stack.pop()
                    next_node_id = self._find_next_node(sorted_structures, j, node_id_map)
                    if next_node_id:
                        for end_node in set(prev_if_info['path_end_nodes']): 
                            if f"{end_node} --> {next_node_id}" not in edge_set:
                                edge_defs.append(f"    {end_node} --> {next_node_id}")
                                edge_set.add(f"{end_node} --> {next_node_id}")
                        if prev_if_info.get('true_next_node'):
                            if f"{prev_if_info['if_node_id']} -->|TRUE| {prev_if_info['true_next_node']}" not in edge_set:
                                edge_defs.append(f"    {prev_if_info['if_node_id']} -->|TRUE| {prev_if_info['true_next_node']}")
                                edge_set.add(f"{prev_if_info['if_node_id']} -->|TRUE| {prev_if_info['true_next_node']}")
                        has_else_path = any(edge.startswith(f"    {prev_if_info['if_node_id']} -->|FALSE|") for edge in edge_defs)
                        if not has_else_path and f"{prev_if_info['if_node_id']} -->|FALSE| {next_node_id}" not in edge_set:
                            edge_defs.append(f"    {prev_if_info['if_node_id']} -->|FALSE| {next_node_id}")
                            edge_set.add(f"{prev_if_info['if_node_id']} -->|FALSE| {next_node_id}")
                        current_node_id = next_node_id

        return edge_defs

    def _find_next_node(self, sorted_structures, current_index, node_id_map):
        """
        次のノードを探すヘルパーメソッド
        """
        for k in range(current_index + 1, len(sorted_structures)):
            next_struct = sorted_structures[k]
            if next_struct['type'] not in ['END_IF', 'ELSE_IF', 'ELSE']:
                if next_struct['type'] == 'LOGICAL_IF':
                    return node_id_map.get(f"{next_struct['line']}_stmt") or node_id_map.get(f"{next_struct['line']}_cond")
                return node_id_map.get(next_struct['line'])
        return None

    def _generate_mermaid_file(self, base_name, unit_index, unit_data, node_defs, edge_defs):
        """
        フェーズ4: Mermaidファイルを生成します。
        """
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
            print(f"Mermaidファイルの保存中にエラーが発生しました: {e}")