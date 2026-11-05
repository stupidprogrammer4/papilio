"""Typed path parameter dependencies."""

from inspect import Parameter, Signature
from typing import Callable

from papilio.core import resources
from papilio.errors.exceptions import NotFoundException
from papilio.tools.ids import IDEncryption


def decode_path_id(
    encryption: IDEncryption,
    entity: str,
    param: str = "id",
) -> Callable[..., int]:
    """Take the public id out of the path and hand the handler the real one.

    The inbound half of `BaseIDOutput`: the route keeps speaking public ids,
    the
    service keeps speaking row ids, and neither has to know about the other::

        OrderID = Annotated[int, Depends(decode_path_id(ORDER_IDS, "Order"))]

        @router.get("/{id}")
        async def get(id: OrderID, service: FromDishka[IOrderService]): ...

    A public id that does not decode is a 404, not a 400 — a forged id is
    indistinguishable from one that never existed, and saying which would turn
    the endpoint into an oracle for valid ids.

    Args:
        encryption (IDEncryption): The mapping the entity's ids were encoded
            with.
        entity (str): Entity name for the 404 body.
        param (str): The path parameter to read.
    Returns:
        (Callable[..., int]): A dependency returning the decoded row id.
    """

    def resolve(**path: int) -> int:
        public_id = path[param]
        internal = encryption.try_decode(public_id)
        if internal is None:
            raise NotFoundException(
                message=f"No {entity} with id '{public_id}'",
                message_code=resources.NOT_FOUND_ERROR,
                entity=entity,
                identifier="id",
                identifier_value=public_id,
                identifier_is_public=True,
            )
        return internal

    # FastAPI reads the signature to know which path param to inject; **path
    # alone would tell it nothing
    resolve.__signature__ = Signature(
        [Parameter(param, Parameter.POSITIONAL_OR_KEYWORD, annotation=int)]
    )
    return resolve
