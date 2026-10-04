"""Register all mapped tables before migrations, API or worker database writes."""

from app.domains.applications.models import AppRecord  # noqa: F401
from app.domains.audit.models import AuditRecord  # noqa: F401
from app.domains.auth.models import AuthSession, RateBucket, User  # noqa: F401
from app.domains.distribution import models as distribution_models  # noqa: F401
from app.domains.distribution.statistics import DistributionObservation  # noqa: F401
from app.domains.github import models as github_models  # noqa: F401
from app.domains.library import models as library_models  # noqa: F401
from app.domains.storage import models as storage_models  # noqa: F401
from app.domains.system.models import SystemState  # noqa: F401
