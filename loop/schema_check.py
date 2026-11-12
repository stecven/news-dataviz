"""pagelayout.json（PageLayoutDoc 1.0）的 JSON Schema 与**受限子集**校验器。

为什么是手写的而不是 `jsonschema` 包：这个契约只有一份 schema、一个消费者（JS
渲染器）、一个生产者（`loop/`），而它要长期冻结。引入一个上千行的第三方校验器，
就把「契约的语义」外包给了一个会独立演进的依赖；而这里的语义很小 —— 递归、按
`type` / `enum` / `required` / `additionalProperties` / `items` 判几条规则而已。
`schema_check.py` 存在的意义是**让 schema 与 `loop/models.py` 的描述漂移时大声
报错**（Spec §5.7 / D12），所以要小到能一眼读完。

`schema` 是**目标 1.0 契约**：老样本缺 `version` / `theme`，六份连 `images` 键
都没有，它们今天必然校验失败。这不是缺陷，是「历史样本今天全红」的可执行版本
（Spec §7 V5）。

`SUPPORTED_KEYWORDS` 是白名单：schema 里出现任何不在其中的关键字都会被
`unsupported_keywords()` 判为错。这样做是因为 JS 侧只打算实现这一小撮关键字，
多一个 "支持" 的幻觉就多一处两边行为不一致的地方。两个例外都在
`unsupported_keywords()` 里单独兜住：`$ref` 的**取值**必须是同文档的
`#/$defs/...`（跨文档引用要在编写期就报，不能留到运行时）；`enum` / `default`
（以及不受支持的 `const`）的**取值位是数据不是关键字**，不再下探。
"""
import json
import os

#: 校验器实现的关键字。schema 用到别的就当错误报出来 —— 宁可校验器小，
#: 也不要出现「schema 写了、JS 却忽略」的静默漂移。
#: 注意 `$ref` **不在**这个集合里：它是关键字，但取值受约束，由
#: `unsupported_keywords()` 用 `_REF_KEYWORD` / `_REF_PREFIX` 单独校验，
#: 免得「白名单里有它」就等于「写什么 $ref 都放行」。
SUPPORTED_KEYWORDS = frozenset({
    "$schema", "$id", "$defs",
    "title", "description",
    "type", "properties", "required", "additionalProperties", "items", "enum",
    "minimum", "maximum", "default",
})

#: 唯一允许的 `$ref` 形态：同一份文档内的 `$defs` 引用。
_REF_KEYWORD = "$ref"
_REF_PREFIX = "#/$defs/"

#: 这些关键字的**取值是数据、不是 schema**：下探就会把数据里的键误报成
#: 「不支持的关键字」（例如 `{"default": {"kind": "thermometer"}}`）。
#: `const` 一并列在这里，是为了它将来被支持时不会再犯同一个错。
_OPAQUE_VALUE_KEYWORDS = ("enum", "default", "const")

#: `loop/` 与 `frontend/` 是仓库根下的兄弟目录，所以从这里上去两级。
SCHEMA_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "frontend", "schema", "pagelayout.schema.json")


def load_schema(path: str = SCHEMA_PATH) -> dict:
    """读入 schema（默认是 `frontend/schema/pagelayout.schema.json`）。"""
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _is_type(value, name: str) -> bool:
    """JSON Schema 的 `type` 断言。注意 bool 不是 integer/number（JSON 语义）。"""
    if name == "object":
        return isinstance(value, dict)
    if name == "array":
        return isinstance(value, list)
    if name == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if name == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if name == "string":
        return isinstance(value, str)
    if name == "boolean":
        return isinstance(value, bool)
    if name == "null":
        return value is None
    return False


def _kind(value) -> str:
    """实际取值的类型名，用来拼人类能读的错误消息。"""
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int):
        return "int"
    if isinstance(value, float):
        return "float"
    if isinstance(value, str):
        return "str"
    if isinstance(value, list):
        return "list"
    if isinstance(value, dict):
        return "dict"
    return type(value).__name__


def _check(node, schema, root, path, errors) -> None:
    """递归校验一个节点，错误 append 成 `{"path": ..., "message": ...}`。

    路径口径：对象键用点号（`$.cards[0].spec.elements[1].x_in`），数组下标用
    方括号（`...[1]`）。类型不对就**停在这一层**返回 —— 一个取值类型错，不该再
    触发下游一串无关错误。
    """
    if "$ref" in schema:
        ref = schema["$ref"]
        if not ref.startswith("#/$defs/"):
            errors.append({"path": path, "message": f"unsupported $ref: {ref}"})
            return
        return _check(node, root["$defs"][ref[len("#/$defs/"):]], root, path, errors)

    if "type" in schema:
        allowed = schema["type"]
        allowed = allowed if isinstance(allowed, list) else [allowed]
        if not any(_is_type(node, t) for t in allowed):
            errors.append({"path": path,
                           "message": f"expected {' | '.join(allowed)}, got {_kind(node)}"})
            return

    if "enum" in schema and not any(node == v for v in schema["enum"]):
        errors.append({"path": path, "message": f"expected one of {schema['enum']!r}"})

    if isinstance(node, (int, float)) and not isinstance(node, bool):
        if "minimum" in schema and node < schema["minimum"]:
            errors.append({"path": path, "message": f"< minimum {schema['minimum']}"})
        if "maximum" in schema and node > schema["maximum"]:
            errors.append({"path": path, "message": f"> maximum {schema['maximum']}"})

    if isinstance(node, dict):
        for key in schema.get("required", []):
            if key not in node:
                errors.append({"path": f"{path}.{key}", "message": "required key is missing"})
        props = schema.get("properties", {})
        if schema.get("additionalProperties") is False:
            for key in node:
                if key not in props:
                    errors.append({"path": f"{path}.{key}", "message": "unknown key"})
        for key, sub in props.items():
            if key in node:
                _check(node[key], sub, root, f"{path}.{key}", errors)

    if isinstance(node, list) and "items" in schema:
        for i, item in enumerate(node):
            _check(item, schema["items"], root, f"{path}[{i}]", errors)


def validate_doc(doc, schema: dict | None = None) -> list[dict]:
    """校验一份 pagelayout 文档，返回错误列表（空列表 = 通过）。"""
    if schema is None:
        schema = load_schema()
    errors: list[dict] = []
    _check(doc, schema, schema, "$", errors)
    return errors


#: 在 `properties` / `$defs` 底下，键是**名字**（字段名 / 定义名），不是关键字。
_NAME_SLOTS = ("properties", "$defs")


def unsupported_keywords(schema, path: str = "$") -> list[str]:
    """列出 schema 里用到的、`SUPPORTED_KEYWORDS` 之外的关键字路径。

    「关键字位」与「属性名位」必须分开看：`properties` / `$defs` 的值是**名字
    表**，`{"properties": {"lines": ...}}` 里的 `lines` 是字段名；而
    `{"lines": {"type": ...}}` 里的 `type` 是关键字。所以只有当**当前节点的
    路径**不是名字槽（不以 `.properties` / `.$defs` 结尾）时，它的键才需要过
    白名单。

    两处例外单独处理：

    * `$ref` 的取值必须形如 `#/$defs/...`。跨文档 / 指别处的引用在这里就被
      拦下，而不是等 `validate_doc()` 真的走到那个节点才报 —— 藏在校验器覆盖
      不到的分支里，就等于静默存在。
    * `enum` / `default`（以及 `const`）的取值是**数据**，不是 schema，不下探。
    """
    bad: list[str] = []
    if isinstance(schema, dict):
        in_name_slot = path.rsplit(".", 1)[-1] in _NAME_SLOTS
        for key, value in schema.items():
            child_path = f"{path}.{key}"
            if in_name_slot:                      # 这一层是名字表：键是字段名/定义名
                bad.extend(unsupported_keywords(value, child_path))
                continue
            if key == _REF_KEYWORD:
                if not (isinstance(value, str) and value.startswith(_REF_PREFIX)):
                    bad.append(child_path)
                continue
            if key not in SUPPORTED_KEYWORDS:
                bad.append(child_path)
            if key in _OPAQUE_VALUE_KEYWORDS:
                continue                          # 取值位不透明，不下探
            bad.extend(unsupported_keywords(value, child_path))
    elif isinstance(schema, list):
        for i, item in enumerate(schema):
            bad.extend(unsupported_keywords(item, f"{path}[{i}]"))
    return bad
