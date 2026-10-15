"""Registry of all ORM models so ``Base.metadata`` knows every table.

Every module that defines models must be imported here.
"""

from app.modules.audit import models as audit_models  # noqa: F401
from app.modules.companies import models as company_models  # noqa: F401
from app.modules.config import models as config_models  # noqa: F401
from app.modules.identity import models as identity_models  # noqa: F401
from app.modules.licences import models as licence_models  # noqa: F401
