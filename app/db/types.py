from enum import Enum

from sqlalchemy.types import String


class EnumType[T]:
    """
    Store Python enums as VARCHAR while returning Enum instances.
    """

    impl = String

    cache_ok = True

    def __init__(self, enum_class: type[Enum]):
        super().__init__()
        self.enum_class = enum_class

        self.impl = String(max(len(member.value) for member in enum_class))

    def process_bind_param(self, value, dialect):
        if value is None:
            return None

        if isinstance(value, self.enum_class):
            try:
                return self.enum_class(value).value
            except ValueError:
                raise ValueError(f"{value!r} is not a valid {self.enum_class.__name__}")  # noqa: B904

        raise TypeError(...)

    def process_result_value(self, value, dialect):
        if value is None:
            return None

        return self.enum_class(value)
