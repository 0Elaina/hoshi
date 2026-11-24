from hoshi.api.dependencies import SessionDependency
from hoshi.modules.user.repository import UserRepository
from hoshi.modules.user.service import AccountQueryService


def get_account_query_service(session: SessionDependency) -> AccountQueryService:
    return AccountQueryService(session, user_repository=UserRepository(session))
