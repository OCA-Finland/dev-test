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
            return request.make_json_response({'error': 'Avaintoiminnot edellyttävät HTTPS-yhteyttä.'}, status=403)
        try:
            backend = request.env['vero.api.backend'].browse(backend_id).exists()
            if not backend:
                raise AccessError('')
            result = backend._credential_operation(operation, values)
        except (AccessError, MissingError):
            request.env.cr.rollback()
            return request.make_json_response({'error': 'Sinulla ei ole oikeutta tämän yrityksen Vero API -avaimiin.'}, status=403)
        except CredentialError as exc:
            request.env.cr.rollback()
            return request.make_json_response({'error': str(exc)}, status=400)
        except Exception:
            # Neither traceback nor third-party messages may echo submitted values.
            request.env.cr.rollback()
            return request.make_json_response({'error': 'Toiminto epäonnistui. Päivitä noudon tila ennen uutta yritystä.'}, status=400)
        finally:
            values.clear()
        return request.make_json_response(result, headers=[('Cache-Control', 'no-store')])
