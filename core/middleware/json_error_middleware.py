from http import HTTPStatus
from django.http import JsonResponse

class JSONErrorMiddleware:
    """Without this middleware, APIs would respond with
    html/text whenever there's an error.
    This middleware converts the response to JSON."""
    def __init__(self, get_response):
        self.get_response = get_response
        self.status_code_description = {
            v.value: v.phrase for v in HTTPStatus
        }

    def __call__(self, request):
        response = self.get_response(request)
        
        status_code = response.status_code
        if (not HTTPStatus.BAD_REQUEST < status_code
            <= HTTPStatus.INTERNAL_SERVER_ERROR):
            return response

        # Return a JSON error response if any of 403, 404, or 500 occurs.
        r = JsonResponse({
            "error": {
                "status_code": status_code,
                "message": self.status_code_description[status_code],
            }
        })

        r.status_code = status_code
        return r