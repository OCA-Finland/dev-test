from odoo import http
from odoo.http import request
from odoo.exceptions import AccessError, MissingError
from ..vero_credentials import CredentialError


class VeroCredentialsController(http.Controller):
    @http.route('/vero/credentials/<int:backend_id>/<string:operation>', type='http',
                auth='user', methods=['POST'], csrf=True, max_content_length=16384)
    def credentials(self, backend_id, operation, **values):
        # HTTP form, not JSON-RPC: call_kw's debug logging must not see secrets.
        if not request.httprequest.is_secure:
            return request.make_json_response({'error': request.env._('Credential operations require HTTPS.')}, status=403)
        try:
            backend = request.env['vero.api.backend'].browse(backend_id).exists()
            if not backend:
                raise AccessError('')
            result = backend._credential_operation(operation, values)
        except (AccessError, MissingError):
            request.env.cr.rollback()
            return request.make_json_response({'error': request.env._("You do not have access to this company's Vero API credentials.")}, status=403)
        except CredentialError as exc:
            request.env.cr.rollback()
            return request.make_json_response({'error': exc.translated(request.env._)}, status=400)
        except Exception:
            # Neither traceback nor third-party messages may echo submitted values.
            request.env.cr.rollback()
            return request.make_json_response({'error': request.env._('The operation failed. Refresh the retrieval status before trying again.')}, status=400)
        finally:
            values.clear()
        return request.make_json_response(result, headers=[('Cache-Control', 'no-store')])
