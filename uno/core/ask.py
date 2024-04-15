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
# From https://stackoverflow.com/a/3041990, slightly modified
import sys
import os


from .log import Logger

log = Logger.sublogger("ask")


QUERY_ASSUME_YES = False


def ask_assume_yes(value: bool = True):
  global QUERY_ASSUME_YES
  QUERY_ASSUME_YES = value


QUERY_ASSUME_NO = False


def ask_assume_no(value: bool = True):
  global QUERY_ASSUME_NO
  QUERY_ASSUME_NO = value


def ask_yes_no(question, full_answer=False, return_answer: bool = False) -> bool:
  if QUERY_ASSUME_NO:
    log.debug(question)
    log.debug("assuming 'no' answer.")
    if not return_answer:
      raise RuntimeError("command aborted on question", question)
    return False
  elif QUERY_ASSUME_YES:
    log.debug(question)
    log.debug("assuming 'yes' answer.")
    return True

  if len(os.getenv("CI", "")) > 0:
    log.error(question)
    log.error("assuming 'no' answer because environment variable CI is set")
    return False

  valid = {"Yes": True, "No": False}
  if not full_answer:
    valid.update(
      {
        "y": True,
        "Y": True,
        "n": False,
        "N": False,
        "yes": True,
        "YES": True,
        "no": False,
        "NO": False,
      }
    )
    prompt = " [y/N] "
  else:
    prompt = " [Yes/No] "

  while True:
    sys.stdout.write(question + prompt)
    choice = input()
    if choice == "":
      result = valid["No"]
      break
    elif choice in valid:
      result = valid[choice]
      break
    else:
      if full_answer:
        sys.stdout.write("\nPlease respond with 'Yes' or 'No'.\n\n")
      else:
        sys.stdout.write("\nPlease respond with 'yes' or 'no' " "(or 'y' or 'n').\n\n")

  if not result and not return_answer:
    raise RuntimeError("command aborted on 'no' answer to question")

  return result
