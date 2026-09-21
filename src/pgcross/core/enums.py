from enum import IntEnum, Enum

class Tier(IntEnum):                      # ORDINAL so floor = min()
    Open = 0; Wf = 1; Dr = 2; finite_diagnostic = 3; Th_coqc = 4

class CType(str, Enum):
    COMPUTED="COMPUTED"; RETRIEVED="RETRIEVED"; LENS="LENS"
    GUESS="GUESS"; CLARIFY="CLARIFY"; CONSULTATION="CONSULTATION"

class Verifiability(str, Enum):
    COQ_CHECKED="COQ_CHECKED"; INDEPENDENT_ORACLE="INDEPENDENT_ORACLE"
    SOURCE_ATTRIBUTED="SOURCE_ATTRIBUTED"; SELF_CONSISTENT="SELF_CONSISTENT"; NONE="NONE"

class RoutingCertainty(str, Enum):
    SYMBOLIC="SYMBOLIC"; DENSE_CLEAR="DENSE_CLEAR"; DENSE_WEAK="DENSE_WEAK"; NONE="NONE"

class Grounding(str, Enum):
    ALL="ALL"; PARTIAL="PARTIAL"; NONE="NONE"

class Stakes(str, Enum):
    LOW="LOW"; HIGH="HIGH"

ASSERTIVE = {CType.COMPUTED, CType.RETRIEVED}        # gated in HIGH stakes
ALWAYS_ALLOWED = {CType.LENS, CType.CLARIFY, CType.CONSULTATION}
