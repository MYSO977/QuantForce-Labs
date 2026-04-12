"""Strategy Artifact Schema (兼容 pydantic / 纯 Python 降级)"""
try:
    from pydantic import BaseModel, Field
    from typing import Literal, Dict
    class ArtifactSchema(BaseModel):
        strategy_id: str
        version: str
        status: Literal["shadow","canary","live","deprecated"] = "shadow"
        source: Dict = {}
        performance: Dict = {}
        config: Dict = {}
        deployment: Dict = {}
        class Config: extra = "allow"
    SchemaClass = ArtifactSchema
except ImportError:
    SchemaClass = dict  # 无 pydantic 时降级为字典校验

def validate_artifact(data: dict) -> bool:
    req = ["strategy_id", "version", "shadow_mode", "parameters"]
    missing = [k for k in req if k not in data]
    if missing:
        raise ValueError(f"缺失必要字段: {missing}")
    return True
