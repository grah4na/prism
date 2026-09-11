import os

import yaml


def _compose_path() -> str:
    here = os.path.dirname(os.path.abspath(__file__))
    for cand in (
        os.path.join(here, "..", "config", "compose.yml"),
        os.path.join(here, "..", "docker-compose.yml"),
        "../docker-compose.yml",
    ):
        if os.path.exists(cand):
            return cand
    return os.path.join(here, "..", "config", "compose.yml")


def main() -> None:
    print("### HTTP Servers")
    print("|-|")
    with open(_compose_path(), encoding="utf-8") as f:
        for service_name, service_props in yaml.safe_load(f)["services"].items():
            if "x-props" not in service_props:
                continue
            x_props = service_props["x-props"]
            if x_props["role"] == "origin":
                print(f"| [{service_name}]({service_props['build']['args'].get('APP_REPO')}) |")
    print()

    print("### HTTP Transducers")
    print("|-|")
    with open(_compose_path(), encoding="utf-8") as f:
        for service_name, service_props in yaml.safe_load(f)["services"].items():
            if "x-props" not in service_props:
                continue
            x_props = service_props["x-props"]
            if x_props["role"] == "transducer":
                print(f"| [{service_name}]({service_props['build']['args'].get('APP_REPO')}) |")


if __name__ == "__main__":
    main()
