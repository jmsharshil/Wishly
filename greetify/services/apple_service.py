import jwt
import requests
from django.conf import settings
from rest_framework.exceptions import AuthenticationFailed

def verify_apple_id_token(token: str) -> dict:
    """
    Verifies the Apple ID token signature, issuer, and client audience.
    """
    # 1. Local mock bypass for debug testing
    if settings.DEBUG and token == 'mock-apple-token':
        return {
            'apple_id': 'mock-apple-id-12345',
            'email': 'mockappleuser@example.com',
            'first_name': 'MockApple',
            'last_name': 'User',
        }

    try:
        # 2. Get Key ID (kid) from token header
        unverified_header = jwt.get_unverified_header(token)
        kid = unverified_header.get('kid')
        alg = unverified_header.get('alg', 'RS256')
        
        # 3. Retrieve active public signing keys from Apple
        response = requests.get("https://appleid.apple.com/auth/keys")
        if response.status_code != 200:
            raise AuthenticationFailed("Failed to fetch public keys from Apple.")
        jwks = response.json()
        
        # 4. Extract matching RSA public key
        public_key = None
        for key in jwks.get('keys', []):
            if key.get('kid') == kid:
                public_key = jwt.algorithms.RSAAlgorithm.from_jwk(key)
                break
                
        if not public_key:
            raise AuthenticationFailed("Apple signature key not found in JWKS.")
            
        # 5. Verify signature, expiry, and app Bundle ID audience
        client_id = getattr(settings, 'APPLE_CLIENT_ID', None)
        id_info = jwt.decode(
            token,
            public_key,
            algorithms=[alg],
            audience=client_id,
            options={"verify_signature": True}
        )
        
        if id_info.get('iss') != 'https://appleid.apple.com':
            raise AuthenticationFailed('Invalid issuer for Apple token.')
            
        return {
            'apple_id': id_info.get('sub'),
            'email': id_info.get('email'),
        }
    except Exception as e:
        raise AuthenticationFailed(f'Invalid Apple token: {str(e)}')
