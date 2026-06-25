import os
import logging
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import sqlglot
from sqlglot import exp

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("sql-lineage")

app = FastAPI(title="SQL Lineage Visualizer API")

@app.get("/")
async def get_index():
    return FileResponse(os.path.join(os.path.dirname(__file__), "index.html"))

@app.get("/api/health")
async def health_check():
    return {"status": "ok"}

# Enable CORS for local development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class AnalyzeRequest(BaseModel):
    sql_string: str
    dialect: str | None = None

class ReferencedTable(BaseModel):
    name: str
    alias: str | None = None
    role: str

class NodeData(BaseModel):
    label: str
    nodeType: str  # "source" | "cte" | "target"
    referenced_tables: list[ReferencedTable] | None = None
    aliases: list[str] | None = None
    columns: list[str] | None = None

class LineageNode(BaseModel):
    id: str
    type: str  # always "custom"
    data: NodeData

class LineageEdge(BaseModel):
    id: str
    source: str
    target: str
    type: str = "smoothstep"
    animated: bool = True

class ColumnEdge(BaseModel):
    source_node: str
    source_col: str
    target_node: str
    target_col: str

class AnalyzeResponse(BaseModel):
    nodes: list[LineageNode]
    edges: list[LineageEdge]
    column_edges: list[ColumnEdge] = []

def get_selects_outside_ctes(node: exp.Expression) -> list[exp.Select]:
    """
    Recursively extract Select nodes from an expression, 
    but do not descend into CTE definitions.
    """
    selects = []
    
    def recurse(curr):
        if not curr or not isinstance(curr, exp.Expression):
            return
        if isinstance(curr, exp.CTE):
            # Skip traversing the CTE definition itself
            return
        if isinstance(curr, exp.Select):
            selects.append(curr)
        
        # Iterate over all arguments/child expressions
        for arg in curr.args.values():
            if isinstance(arg, list):
                for val in arg:
                    recurse(val)
            elif isinstance(arg, exp.Expression):
                recurse(arg)
                
    recurse(node)
    return selects

def get_tables_outside_ctes(node: exp.Expression) -> list[exp.Table]:
    """
    Recursively extract Table nodes from an expression, 
    but do not descend into CTE definitions.
    This helps us identify only the direct table dependencies at the current query scope.
    """
    tables = []
    
    def recurse(curr):
        if not curr or not isinstance(curr, exp.Expression):
            return
        if isinstance(curr, exp.CTE):
            # Skip traversing the CTE definition itself
            return
        if isinstance(curr, exp.Table):
            tables.append(curr)
            # Typically Table nodes have no sub-tables, but we return to be safe
            return
        
        # Iterate over all arguments/child expressions
        for arg in curr.args.values():
            if isinstance(arg, list):
                for val in arg:
                    recurse(val)
            elif isinstance(arg, exp.Expression):
                recurse(arg)
                
    recurse(node)
    return tables

def extract_query_relations(query_node: exp.Expression, cte_names: set):
    driving_table = None
    joined_tables = []
    
    selects = get_selects_outside_ctes(query_node)
    for select in selects:
        # Check FROM clause
        from_node = select.args.get("from")
        if from_node:
            table_node = from_node.find(exp.Table)
            if table_node:
                parts = [p.name for p in table_node.parts]
                actual_name = ".".join(parts)
                alias = table_node.alias
                driving_table = {
                    "name": actual_name,
                    "alias": alias if alias else None,
                    "role": "DRIVING"
                }
        
        # Check JOIN clauses
        joins = select.args.get("joins") or []
        for join in joins:
            table_node = join.find(exp.Table)
            if table_node:
                parts = [p.name for p in table_node.parts]
                actual_name = ".".join(parts)
                alias = table_node.alias
                
                # Determine join type
                side = join.args.get("side")
                method = join.args.get("method")
                join_parts = []
                if side:
                    join_parts.append(side.upper())
                if method:
                    join_parts.append(method.upper())
                join_parts.append("JOIN")
                join_type = " ".join(join_parts)
                
                joined_tables.append({
                    "name": actual_name,
                    "alias": alias if alias else None,
                    "role": join_type
                })
                
    return driving_table, joined_tables

def resolve_column_edges(query_node: exp.Expression, target_node_id: str, cte_names: set):
    col_edges = []
    selects = get_selects_outside_ctes(query_node)
    
    for select in selects:
        # Build table alias lookup map for this Select scope
        alias_map = {}
        driving_name = None
        
        # FROM clause
        from_node = select.args.get("from")
        if from_node:
            table_node = from_node.find(exp.Table)
            if table_node:
                parts = [p.name for p in table_node.parts]
                actual_name = ".".join(parts).lower()
                driving_name = actual_name
                alias = table_node.alias
                if alias:
                    alias_map[alias.lower()] = actual_name
                # Also index by actual name so lookups without alias work
                alias_map[actual_name.split(".")[-1]] = actual_name
        
        # JOIN clauses
        joins = select.args.get("joins") or []
        for join in joins:
            table_node = join.find(exp.Table)
            if table_node:
                parts = [p.name for p in table_node.parts]
                actual_name = ".".join(parts).lower()
                alias = table_node.alias
                if alias:
                    alias_map[alias.lower()] = actual_name
                alias_map[actual_name.split(".")[-1]] = actual_name

        # Parse expressions
        for expr in select.expressions:
            if isinstance(expr, exp.Alias):
                target_col = expr.alias
                source_expr = expr.this
            else:
                target_col = expr.name if hasattr(expr, "name") and expr.name else expr.sql()
                source_expr = expr

            cols_in_expr = list(source_expr.find_all(exp.Column))
            if not cols_in_expr:
                continue
                
            for col in cols_in_expr:
                col_name = col.name
                table_alias = col.text("table")
                
                resolved_table_id = None
                if table_alias:
                    resolved_table_id = alias_map.get(table_alias.lower())
                
                if not resolved_table_id:
                    resolved_table_id = driving_name
                
                if resolved_table_id:
                    col_edges.append({
                        "source_node": resolved_table_id,
                        "source_col": col_name,
                        "target_node": target_node_id,
                        "target_col": target_col
                    })
                    
    return col_edges


@app.post("/api/analyze", response_model=AnalyzeResponse)
async def analyze_sql(payload: AnalyzeRequest):
    sql_text = payload.sql_string.strip()
    if not sql_text:
        return AnalyzeResponse(nodes=[], edges=[], column_edges=[])

    dialect = payload.dialect or None
    try:
        # sqlglot.parse can parse multiple statements separated by semicolons
        expressions = sqlglot.parse(sql_text, read=dialect)
    except Exception as e:
        logger.error(f"SQL parsing error with dialect {dialect}: {e}")
        raise HTTPException(
            status_code=400,
            detail=f"Failed to parse SQL query (Dialect: {dialect or 'Standard'}): {str(e)}"
        )

    nodes_map = {}  # id -> {label, type, referenced_tables, columns}
    edges_set = set()  # set of (source_id, target_id)
    source_aliases = {}  # id -> list of alias strings
    all_column_edges = []

    # 1. Collect all CTE definitions first across all statements
    cte_names = set()
    for expr in expressions:
        if not expr:
            continue
        for cte in expr.find_all(exp.CTE):
            cte_names.add(cte.alias_or_name.lower())

    # 2. Process each expression/statement
    for idx, expr in enumerate(expressions):
        if not expr:
            continue

        # Detect target/destination table schema-qualified
        target_table_name = None
        is_insert = isinstance(expr, exp.Insert)
        is_create = isinstance(expr, exp.Create)

        if is_insert:
            target_table_node = expr.find(exp.Table)
            if target_table_node:
                target_table_name = ".".join(p.name for p in target_table_node.parts)
        elif is_create:
            target_table_node = expr.find(exp.Table)
            if target_table_node:
                target_table_name = ".".join(p.name for p in target_table_node.parts)
        
        # If there's no insert/create, check if it's a select statement
        if not target_table_name:
            if expr.find(exp.Select):
                target_table_name = f"Final Output" if len(expressions) == 1 else f"Final Output {idx + 1}"
            else:
                continue

        target_id = target_table_name.lower()
        nodes_map[target_id] = {
            "label": target_table_name,
            "type": "target",
            "referenced_tables": [],
            "columns": []
        }

        # Find all CTEs defined in this specific statement
        local_ctes = {}
        for cte in expr.find_all(exp.CTE):
            cte_name = cte.alias_or_name.lower()
            local_ctes[cte_name] = cte.this
            nodes_map[cte_name] = {
                "label": cte.alias_or_name,
                "type": "cte",
                "referenced_tables": [],
                "columns": []
            }

        # Map dependencies for CTEs
        for cte_name, cte_query in local_ctes.items():
            driving, joined = extract_query_relations(cte_query, cte_names)
            referenced_metadata = []
            
            if driving:
                referenced_metadata.append(driving)
                ref_name_lower = driving["name"].lower()
                edges_set.add((ref_name_lower, cte_name))
                if ref_name_lower not in cte_names:
                    nodes_map[ref_name_lower] = {
                        "label": driving["name"],
                        "type": "source",
                        "columns": []
                    }
                    alias_str = f"{driving['alias']} (in {cte_name})" if driving["alias"] else f"None (in {cte_name})"
                    source_aliases.setdefault(ref_name_lower, []).append(alias_str)
                    
            for j in joined:
                referenced_metadata.append(j)
                ref_name_lower = j["name"].lower()
                edges_set.add((ref_name_lower, cte_name))
                if ref_name_lower not in cte_names:
                    nodes_map[ref_name_lower] = {
                        "label": j["name"],
                        "type": "source",
                        "columns": []
                    }
                    alias_str = f"{j['alias']} (in {cte_name})" if j["alias"] else f"None (in {cte_name})"
                    source_aliases.setdefault(ref_name_lower, []).append(alias_str)
                    
            nodes_map[cte_name]["referenced_tables"] = referenced_metadata

            # Extract columns for this CTE
            cte_cols = []
            selects = get_selects_outside_ctes(cte_query)
            for s in selects:
                for col_expr in s.expressions:
                    if isinstance(col_expr, exp.Alias):
                        cte_cols.append(col_expr.alias)
                    else:
                        cte_cols.append(col_expr.name if hasattr(col_expr, "name") and col_expr.name else col_expr.sql())
            nodes_map[cte_name]["columns"] = list(dict.fromkeys(cte_cols))

            # Resolve column-level edges for this CTE
            cte_col_edges = resolve_column_edges(cte_query, cte_name, cte_names)
            all_column_edges.extend(cte_col_edges)

        # Map dependencies for the main target table
        source_query_node = expr
        if is_insert and expr.expression:
            source_query_node = expr.expression
        elif is_create and expr.expression:
            source_query_node = expr.expression
            
        driving, joined = extract_query_relations(source_query_node, cte_names)
        referenced_metadata = []
        
        if driving:
            referenced_metadata.append(driving)
            ref_name_lower = driving["name"].lower()
            if ref_name_lower != target_id:
                edges_set.add((ref_name_lower, target_id))
                if ref_name_lower not in cte_names:
                    nodes_map[ref_name_lower] = {
                        "label": driving["name"],
                        "type": "source",
                        "columns": []
                    }
                    alias_str = f"{driving['alias']} (in {target_table_name})" if driving["alias"] else f"None (in {target_table_name})"
                    source_aliases.setdefault(ref_name_lower, []).append(alias_str)
                    
        for j in joined:
            referenced_metadata.append(j)
            ref_name_lower = j["name"].lower()
            if ref_name_lower != target_id:
                edges_set.add((ref_name_lower, target_id))
                if ref_name_lower not in cte_names:
                    nodes_map[ref_name_lower] = {
                        "label": j["name"],
                        "type": "source",
                        "columns": []
                    }
                    alias_str = f"{j['alias']} (in {target_table_name})" if j["alias"] else f"None (in {target_table_name})"
                    source_aliases.setdefault(ref_name_lower, []).append(alias_str)
                    
        nodes_map[target_id]["referenced_tables"] = referenced_metadata

        # Extract columns for this Target table
        target_cols = []
        selects = get_selects_outside_ctes(source_query_node)
        for s in selects:
            for col_expr in s.expressions:
                if isinstance(col_expr, exp.Alias):
                    target_cols.append(col_expr.alias)
                else:
                    target_cols.append(col_expr.name if hasattr(col_expr, "name") and col_expr.name else col_expr.sql())
        nodes_map[target_id]["columns"] = list(dict.fromkeys(target_cols))

        # Resolve column-level edges for this Target table
        target_col_edges = resolve_column_edges(source_query_node, target_id, cte_names)
        all_column_edges.extend(target_col_edges)

    # 3. Populate source node columns from the resolved column edges
    for edge in all_column_edges:
        src = edge["source_node"]
        src_col = edge["source_col"]
        if src in nodes_map and nodes_map[src]["type"] == "source":
            if "columns" not in nodes_map[src] or nodes_map[src]["columns"] is None:
                nodes_map[src]["columns"] = []
            if src_col not in nodes_map[src]["columns"]:
                nodes_map[src]["columns"].append(src_col)

    # Format the nodes and edges for React Flow response
    formatted_nodes = []
    for node_id, data in nodes_map.items():
        node_aliases = None
        if data["type"] == "source":
            node_aliases = list(set(source_aliases.get(node_id, [])))
            
        formatted_nodes.append(
            LineageNode(
                id=node_id,
                type="custom",
                data=NodeData(
                    label=data["label"], 
                    nodeType=data["type"],
                    referenced_tables=data.get("referenced_tables"),
                    aliases=node_aliases,
                    columns=data.get("columns")
                )
            )
        )

    formatted_edges = []
    for src, tgt in edges_set:
        formatted_edges.append(
            LineageEdge(
                id=f"e_{src}_{tgt}",
                source=src,
                target=tgt
            )
        )

    # Format column edges response
    formatted_column_edges = [
        ColumnEdge(
            source_node=e["source_node"],
            source_col=e["source_col"],
            target_node=e["target_node"],
            target_col=e["target_col"]
        ) for e in all_column_edges
    ]

    return AnalyzeResponse(
        nodes=formatted_nodes, 
        edges=formatted_edges,
        column_edges=formatted_column_edges
    )

if __name__ == "__main__":
    import uvicorn
    import os
    # Render or other hosting platforms usually set the PORT environment variable.
    # On production, we also want to host on "0.0.0.0" rather than "127.0.0.1".
    port = int(os.environ.get("PORT", 8000))
    host = "127.0.0.1" if "PORT" not in os.environ else "0.0.0.0"
    reload = "PORT" not in os.environ
    uvicorn.run("main:app", host=host, port=port, reload=reload)
