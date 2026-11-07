from pathlib import Path

DEPLOY = Path(__file__).parents[2] / "deploy"


def test_sysctl_ip_forward_installed_by_install_sh():
    conf = (DEPLOY / "sysctl-altrouter.conf").read_text(encoding="utf-8")
    assert "net.ipv4.ip_forward = 1" in conf
    install = (DEPLOY / "install.sh").read_text(encoding="utf-8")
    assert "/etc/sysctl.d/90-altrouter.conf" in install
    assert "sysctl -p /etc/sysctl.d/90-altrouter.conf" in install
