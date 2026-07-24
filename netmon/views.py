import routeros_api

from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework import filters, status, viewsets
from api.permissions import IsStaffRole

from mclock.crypto_utils import MclockCryptoError, decrypt_password
from django.conf import settings


class MIKROTIKConnectionError(Exception):
    """Gagal terhubung ke MIKROTIK."""

class RouterOSCommandView(APIView):
    permission_classes = [IsAuthenticated, IsStaffRole]


    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        # Router connection configurations
        self.username = 'admin'
        self.port = 8728
        self.connection = None
        self.api = None
        password = settings.MIKROTIK_PASSWORD_ENCRYPTED

        if not password:
            raise MIKROTIKConnectionError(
                'Password MIKROTIK belum diisi (MIKROTIK_PASSWORD_ENCRYPTED di .env).'
            )

        try:
            self.password = decrypt_password(settings.MIKROTIK_PASSWORD_ENCRYPTED)
        except MclockCryptoError as exc:
            raise MIKROTIKConnectionError(str(exc)) from exc

    def initial(self, request, *args, **kwargs):
        """Connect to MikroTik before processing the request."""
        super().initial(request, *args, **kwargs)

        host = kwargs.get('host')
        self.api = None

        try:
            self.connection = routeros_api.RouterOsApiPool(
                host, username=self.username, password=self.password, 
                port=self.port, plaintext_login=True
            )
            self.api = self.connection.get_api()
        except Exception as e:
            raise Exception(f"Failed to connect to RouterOS: {str(e)}")

    def finalize_response(self, request, response, *args, **kwargs):
        """Ensure the connection closes after response is sent."""
        if self.connection:
            self.connection.disconnect()
        return super().finalize_response(request, response, *args, **kwargs)

    def get(self, request, host=None, command=None, format=None):
        """Execute dynamically supplied RouterOS command."""
        import re

        # 1. Make a mutable copy of request.GET
        params = request.GET.copy()

        # 2. Define your regex pattern for keys to remove
        pattern = re.compile(r"^_page|^_limit|^_order|^_sortby")

        # 3. Find and delete keys matching the regex
        for key in list(params.keys()):
            if pattern.match(key):
                del params[key]

        page = int(request.query_params.get('_page', 1))
        limit = int(request.query_params.get('_limit', 10))
        sort_by = request.query_params.get('_sort_by', 'id')
        order = request.query_params.get('_order', 'asc')


        if not command:
            return Response({"error": "Command is required"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            # Replaces URL dash-syntax with slash-syntax for ROS, e.g., 'system-resource' -> '/system/resource'
            # 'ip-dhcp_server-lease' -> '/ip/dhcp-server/lease'

            mapping = {"_": "-", "-": "/"}
            pattern = re.compile("|".join(re.escape(key) for key in mapping.keys()))
            fcmd = pattern.sub(lambda match: mapping[match.group(0)], command)
            formatted_cmd = '/' + fcmd
            result = self.api.get_resource(formatted_cmd).get(**params.dict())

            # 4. Sort Python list (handling strings)
            reverse = True if order == 'desc' else False
            result.sort(key=lambda x: x.get(sort_by, ''), reverse=reverse)

            # 5. Paginate
            start = (page - 1) * limit
            end = start + limit
            paginated_data = result[start:end]
            return Response({
                "command": formatted_cmd,
                "count": len(result),
                "results": paginated_data,
                "next": page + 1 if end < len(result) else None,
                "previous": page - 1 if page > 1 else None,

            }, status=status.HTTP_200_OK)


        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    def post(self,request,host=None,command=None,format=None):
        """Execute dynamically supplied RouterOS command."""
        import re
        if not command:
            return Response({"error": "Command is required"}, status=status.HTTP_400_BAD_REQUEST)
        try:
            # Replaces URL dash-syntax with slash-syntax for ROS, e.g., 'system-resource' -> '/system/resource'
            # 'ip-dhcp_server-lease' -> '/ip/dhcp-server/lease'

            postcmd = request.GET.get('postcmd','')
            mapping = {"_": "-", "-": "/"}
            pattern = re.compile("|".join(re.escape(key) for key in mapping.keys()))
            fcmd = pattern.sub(lambda match: mapping[match.group(0)], command)
            formatted_cmd = '/' + fcmd

            result = self.api.get_resource(formatted_cmd).call(postcmd, request.data)

            return Response({"command": formatted_cmd, "results": result}, status=status.HTTP_200_OK)
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

