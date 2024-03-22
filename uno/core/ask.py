###############################################################################
# (C) Copyright 2020-2024 Andrea Sorbini
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as 
# published by the Free Software Foundation, either version 3 of the 
# License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program. If not, see <https://www.gnu.org/licenses/>.
###############################################################################
# From https://stackoverflow.com/a/3041990, slightly modified
import sys
import os


from .log import Logger
log = Logger.sublogger("ask")


QUERY_ASSUME_YES = False
def ask_assume_yes(value: bool=True):
  global QUERY_ASSUME_YES
  QUERY_ASSUME_YES = value

QUERY_ASSUME_NO = False
def ask_assume_no(value: bool=True):
  global QUERY_ASSUME_NO
  QUERY_ASSUME_NO = value


def ask_yes_no(question, full_answer=False, return_answer: bool=False) -> bool:
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
    valid.update({
      "y": True, "Y": True, "n": False, "N": False,
      "yes": True, "YES": True, "no": False, "NO": False,
    })
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
