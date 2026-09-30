from rest_framework.exceptions import APIException


class SearchUnavailable(APIException):
    status_code = 503
    default_code = "search_unavailable"

    def __init__(self, message: str):
        super().__init__(detail={"error": message})
