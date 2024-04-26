###############################################################################
# Copyright 2020-2024 Andrea Sorbini
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
###############################################################################
import json
from pathlib import Path
from typing import NamedTuple
from datetime import datetime

from pyconfig import sha_short, extract_registries, tuple_to_dict, merge_dicts


###############################################################################
#
###############################################################################
def settings(clone_dir: Path, cfg: NamedTuple, github: NamedTuple) -> dict:
  repo_org, repo = github.repository.split("/")
  repo_url = f"https://github.com/{github.repository}"
  artifacts_dir = Path(github.workspace) / "artifacts"
  #############################################################################
  # Current workflow run settings
  #############################################################################
  ref_sha = sha_short(clone_dir)

  if github.ref_type == "tag":
    build_profile = "stable"
    build_version = github.ref_name
  else:
    build_profile = "nightly"
    build_version = f"{github.ref_name}@{ref_sha}"
  build_version = build_version.replace("/", "-")

  build_date = datetime.now().strftime("%Y%m%d-%H%M%S")

  build_settings_artifact = f"{repo}-settings"

  #############################################################################
  # Container Release settings
  #############################################################################
  release_cfg = getattr(cfg.release.profiles, build_profile)

  release_tag = f"{release_cfg.tag}{release_cfg.tag_suffix}"

  docker_build_platforms = ",".join(release_cfg.build_platforms)

  if release_cfg.tag_suffix is not None:
    docker_flavor_config = f"suffix={release_cfg.tag_suffix},onlatest=true"
  else:
    docker_flavor_config = ""

  prerel_repo = f"{cfg.release.prerelease_repo}-{build_profile}"
  prerel_image = f"{prerel_repo}:{release_tag}"
  prerel_package = (
    ""
    if not cfg.release.prerelease_package
    else (f"{cfg.release.prerelease_package}-{build_profile}")
  )
  if prerel_package:
    prerel_package_org, prerel_package = prerel_package.split("/")
  else:
    prerel_package_org, prerel_package = "", ""
  prerel_registries = extract_registries(
    repo_org,
    [
      release_cfg.base_image,
      prerel_image,
    ],
  )

  release_images = [f"{release_repo}:{release_tag}" for release_repo in cfg.release.final_repos]
  release_registries = extract_registries(
    repo_org,
    [
      *release_images,
      prerel_image,
    ],
  )

  final_repos_config = "\n".join(cfg.release.final_repos)
  final_images_config = "\n".join(release_images)

  if "github" in release_registries:
    gh_release_repo = next(repo for repo in cfg.release.final_repos if repo.startswith("ghcr.io/"))
    gh_package_image = next(img for img in release_images if img.startswith("ghcr.io/"))
    gh_org_package = gh_release_repo.split("ghcr.io/")[1]
    gh_org, gh_package = gh_org_package.split("/")
  else:
    gh_org, gh_package = "", ""
    gh_package_image = ""

  gh_release_url = f"{repo_url}/releases/tag/{github.ref_name}"
  gh_release_create = github.ref_type == "tag"

  release_test_runners_matrix = json.dumps(
    [
      json.dumps(getattr(cfg.ci.runners, platform.replace("/", "_")))
      for platform in release_cfg.build_platforms
    ]
  )

  # A prefix for files generated by the test
  release_test_id = f"release-{build_profile}__{build_version}"
  release_test_artifact = f"{repo}-test-{release_test_id}"
  release_tracker_artifact_prefix = f"{repo}-tracker-{release_test_id}"
  release_tracker_artifact = f"{release_tracker_artifact_prefix}"

  release_tracker_repo_url = f"https://github.com/{cfg.release.tracker.repository.name}"

  release_notes_artifacts_prefix = f"{repo}-notes-{release_test_id}"
  release_notes_artifact = f"{release_notes_artifacts_prefix}"

  badge_filename = github.repository.replace("/", "-") + "-badge-" + build_profile
  badge_base_image = tuple_to_dict(release_cfg.badge.base_image)
  badge_base_image["message"] = release_cfg.base_image
  badge_base_image["filename"] = f"{badge_filename}-base-image.json"
  badge_version = tuple_to_dict(release_cfg.badge.version)
  badge_version["message"] = build_version
  badge_version["filename"] = f"{badge_filename}-version.json"

  #############################################################################
  # Debian packaging settings
  #############################################################################
  debian_enabled = (clone_dir / "debian" / "control").is_file()
  debian_builder_base_images_matrix = json.dumps(cfg.debian.builder.base_images)
  debian_builder_registries = extract_registries(
    repo_org,
    [
      cfg.debian.builder.repo,
      *cfg.debian.builder.base_images,
    ],
  )
  debian_builder_architectures_matrix = json.dumps(cfg.debian.builder.architectures)

  #############################################################################
  # CI infrastructure settings
  #############################################################################
  admin_registries = extract_registries(
    repo_org,
    [
      cfg.ci.images.admin.image,
    ],
  )

  release_base_images = list({release_cfg.base_image for release_cfg in cfg.release.profiles})

  tester_base_images_matrix = json.dumps(release_base_images)
  tester_registries = extract_registries(
    repo_org,
    [
      cfg.ci.images.tester.repo,
      *release_base_images,
    ],
  )

  #############################################################################
  # Output generated settings
  #############################################################################
  return {
    ###########################################################################
    # Build config
    ###########################################################################
    "build": {
      "repository": {
        "name": repo,
        "org": repo_org,
        "url": repo_url,
      },
      "date": build_date,
      "profile": build_profile,
      "settings": {
        "artifact": build_settings_artifact,
      },
      "version": build_version,
      "artifacts_dir": str(artifacts_dir),
    },
    ###########################################################################
    # CI config
    ###########################################################################
    "ci": merge_dicts(
      {
        "images": {
          "admin": {
            "login": {
              "dockerhub": "dockerhub" in admin_registries,
              "github": "github" in admin_registries,
            },
          },
          "tester": {
            "base_images_matrix": tester_base_images_matrix,
            "build_platforms_config": docker_build_platforms,
            "login": {
              "dockerhub": "dockerhub" in tester_registries,
              "github": "github" in tester_registries,
            },
          },
        },
      },
      tuple_to_dict(cfg.ci),
    ),
    ###########################################################################
    # Debian config
    ###########################################################################
    "debian": merge_dicts(
      {
        "enabled": debian_enabled,
        "builder": {
          "base_images_matrix": debian_builder_base_images_matrix,
          "architectures_matrix": debian_builder_architectures_matrix,
          "login": {
            "dockerhub": "dockerhub" in debian_builder_registries,
            "github": "github" in debian_builder_registries,
          },
        },
      },
      tuple_to_dict(cfg.debian),
    ),
    ###########################################################################
    # Release config
    ###########################################################################
    "release": merge_dicts(
      {
        "badge": {
          "base_image": badge_base_image,
          "version": badge_version,
        },
        "build_platforms_config": docker_build_platforms,
        "flavor_config": docker_flavor_config,
        "prerelease_image": prerel_image,
        "prerelease_package": prerel_package,
        "prerelease_package_org": prerel_package_org,
        "prerelease_repo": prerel_repo,
        "final_repos_config": final_repos_config,
        "final_images": release_images,
        "final_images_config": final_images_config,
        "login": {
          "dockerhub": "dockerhub" in release_registries,
          "github": "github" in release_registries,
        },
        "login_prerel": {
          "dockerhub": "dockerhub" in prerel_registries,
          "github": "github" in prerel_registries,
        },
        "gh": {
          "org": gh_org,
          "package": gh_package,
          "package_image": gh_package_image,
          "release": {
            "url": gh_release_url,
            "create": gh_release_create,
          },
        },
        "notes": {
          "artifact": release_notes_artifact,
          "artifacts_prefix": release_notes_artifacts_prefix,
        },
        "tag": release_tag,
        "tags_config": release_cfg.tags_config,
        "test_artifact": release_test_artifact,
        "test_id": release_test_id,
        "test_runners_matrix": release_test_runners_matrix,
        "tracker": {
          "artifact": release_tracker_artifact,
          "artifact_prefix": release_tracker_artifact_prefix,
          "repository": {
            "url": release_tracker_repo_url,
          },
        },
      },
      tuple_to_dict(release_cfg),
    ),
  }