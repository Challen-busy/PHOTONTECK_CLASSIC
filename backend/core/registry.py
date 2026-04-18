"""
模型自动注册 —— 从 SQLAlchemy metadata 扫描,取代手写的 DOC_MODEL_MAP / TABLE_MAP。

约定:
  __doc_types__  = (...)   # 主单据类声明,元组内元素是 WorkflowDefinition.doc_type 的值
                            # 同一个类可对应多个 doc_type(如 Inventory 走 3 套状态机)
  __queryable__  = True    # 纯子表/主数据/日志,Agent query_data 和流程子表操作可见

判定规则:
  - 有 __doc_types__ 的类自动可查(主单据一定可查)
  - 只有 __queryable__ = True 的辅助类才进 table_map
  - 没有任何标注的类(如权限映射表、Admin 审计表)默认内部,Agent 不可见
"""

from functools import lru_cache

from core.database import Base


def _ensure_models_loaded() -> None:
    """确保 models 模块已加载(所有类注册到 Base.registry)。"""
    import models  # noqa: F401


@lru_cache(maxsize=1)
def doc_model_map() -> dict[str, type]:
    """doc_type -> 主模型类。启动时扫描一次并缓存。"""
    _ensure_models_loaded()
    result: dict[str, type] = {}
    for mapper in Base.registry.mappers:
        cls = mapper.class_
        for dt in getattr(cls, "__doc_types__", ()) or ():
            if dt in result and result[dt] is not cls:
                raise RuntimeError(
                    f"doc_type 冲突: '{dt}' 同时被 {result[dt].__name__} 和 {cls.__name__} 声明"
                )
            result[dt] = cls
    return result


@lru_cache(maxsize=1)
def table_map() -> dict[str, type]:
    """table_name -> 模型类。Agent 和流程子表操作可见的表。"""
    _ensure_models_loaded()
    result: dict[str, type] = {}
    for mapper in Base.registry.mappers:
        cls = mapper.class_
        exposed = bool(getattr(cls, "__doc_types__", None)) or bool(getattr(cls, "__queryable__", False))
        if exposed:
            result[cls.__tablename__] = cls
    return result


def doc_types() -> list[str]:
    """所有已注册 doc_type(排序后返回,便于稳定输出)。"""
    return sorted(doc_model_map().keys())
