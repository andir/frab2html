#!/usr/bin/env python

import sys
import re
import json


def fix_json(schedulejson):
    """Fix the broken JSON we get from frab."""
    schedulejson = schedulejson.replace('days', 'num_days', 1)
    schedulejson = schedulejson.replace('\r\n', '\\n')
    schedulejson = schedulejson.replace('\t', ' ')
    schedulejson = schedulejson.replace('&#x27;', "'")
    schedulejson = schedulejson.replace('&amp;', "&")
    schedulejson = schedulejson.replace('&quot;', '\\"')
    schedulejson = schedulejson.replace('&lt;', '<')
    schedulejson = schedulejson.replace('&gt;', '>')
    schedulejson = re.sub(r',\s+"links":([^\]]|[^\s]])+\s]', "", schedulejson)
    schedulejson = re.sub(r'\},\s*\]', "}]", schedulejson)

    return schedulejson

if __name__ == "__main__":
    if len(sys.argv) != 3:
        print "Usage: {0} input output".format(sys.argv[0])
        sys.exit(1)

    with open(sys.argv[1]) as f:
        schedulejson = f.read()

    fixedjson = fix_json(schedulejson)

    # Parse it to make sure it is correct
    schedule = json.loads(fixedjson)

    with open(sys.argv[2], "w") as f:
        json.dump(schedule, f)
