from __future__ import annotations

from datetime import timedelta
from uuid import uuid4


class MockSAMLProvider:
    def __init__(self, *, clock) -> None:
        self.clock = clock
        self.entity_id = "https://mock-saml.local/sp"
        self.metadata_xml = "https://mock-saml.local/metadata"
        self.certificate = "-----BEGIN CERTIFICATE-----\nMIID...\n-----END CERTIFICATE-----"
        self.key = "-----BEGIN PRIVATE KEY-----\nMIIE...\n-----END PRIVATE KEY-----"
        self.audience = self.entity_id

    def env(self) -> dict[str, str]:
        return {
            "SSO_ENABLED": "true",
            "SSO_SESSION_TTL_SECONDS": "900",
            "SSO_BLUE_GREEN_STATE": "green",
            "SAML_SP_ENTITY_ID": self.entity_id,
            "SAML_IDP_METADATA_XML": self.metadata_xml,
            "SAML_SP_CERT_PEM": self.certificate,
            "SAML_SP_KEY_PEM": self.key,
            "SAML_AUDIENCE": self.audience,
        }

    def build_assertion(self, *, role: str, center_scope: str, name_id: str | None = None) -> str:
        now = self.clock.now()
        name_id = name_id or uuid4().hex
        not_before = (now - timedelta(minutes=1)).isoformat()
        not_on_or_after = (now + timedelta(minutes=5)).isoformat()
        return f"""
        <Assertion xmlns="urn:oasis:names:tc:SAML:2.0:assertion">
          <Issuer>mock-idp</Issuer>
          <Subject>
            <NameID>{name_id}</NameID>
          </Subject>
          <Conditions NotBefore="{not_before}" NotOnOrAfter="{not_on_or_after}">
            <AudienceRestriction>
              <Audience>{self.audience}</Audience>
            </AudienceRestriction>
          </Conditions>
          <AttributeStatement>
            <Attribute Name="role">
              <AttributeValue>{role}</AttributeValue>
            </Attribute>
            <Attribute Name="center_scope">
              <AttributeValue>{center_scope}</AttributeValue>
            </Attribute>
          </AttributeStatement>
        </Assertion>
        """.strip()


__all__ = ["MockSAMLProvider"]
