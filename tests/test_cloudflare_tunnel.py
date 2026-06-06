from local_llm_env.reconcile.cloudflare_tunnel import (
    parse_tunnel_id_from_config,
    render_tunnel_config,
    secret_tunnel_credentials,
    secret_tunnel_id,
    tunnel_route_ref,
)


def test_secret_tunnel_id_reads_spec_key():
    cf = {"tunnel_id_secret_key": "CLOUDFLARE_TUNNEL_ID"}
    secrets = {"CLOUDFLARE_TUNNEL_ID": "  abc-123  "}
    assert secret_tunnel_id(cf, secrets) == "abc-123"


def test_secret_tunnel_credentials_normalizes_json():
    cf = {"credentials_file_secret_key": "CF_TUNNEL_CREDENTIALS_JSON"}
    secrets = {
        "CF_TUNNEL_CREDENTIALS_JSON": (
            '{"AccountTag":"acct","TunnelID":"tid","TunnelSecret":"sec"}'
        )
    }
    rendered = secret_tunnel_credentials(cf, secrets)
    assert '"AccountTag": "acct"' in rendered
    assert rendered.endswith("\n")


def test_parse_tunnel_id_from_config():
    config = "tunnel: local-llm\ncredentials-file: ~/.cloudflared/abcd.json\n"
    assert parse_tunnel_id_from_config(config) == ""

    config = "tunnel: 11111111-2222-3333-4444-555555555555\n"
    assert parse_tunnel_id_from_config(config) == "11111111-2222-3333-4444-555555555555"


def test_render_tunnel_config_uses_name_when_id_missing():
    rendered = render_tunnel_config("local-llm", "", [{"hostname": "x.dev", "service": "http://127.0.0.1:1234"}])
    assert "tunnel: local-llm\n" in rendered
    assert "credentials-file:" not in rendered
    assert "hostname: x.dev" in rendered


def test_render_tunnel_config_uses_uuid_when_present():
    tunnel_id = "11111111-2222-3333-4444-555555555555"
    rendered = render_tunnel_config("local-llm", tunnel_id, [])
    assert f"tunnel: {tunnel_id}\n" in rendered
    assert f"credentials-file: ~/.cloudflared/{tunnel_id}.json\n" in rendered


def test_tunnel_route_ref_prefers_uuid():
    tunnel_id = "11111111-2222-3333-4444-555555555555"
    assert tunnel_route_ref(tunnel_id, "local-llm") == tunnel_id
    assert tunnel_route_ref("", "local-llm") == "local-llm"
