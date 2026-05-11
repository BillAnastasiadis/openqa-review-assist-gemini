import argparse
import requests
import json
from collections import Counter
from sanitizer import sanitize_text
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

OPENQA_BASE_URL = "https://openqa.suse.de"
API_TIMEOUT = 45

def extract_top_10(text):
    lines = text.strip().splitlines()
    if len(lines) > 10:
        return "\n".join(lines[:10]) + "\n... [truncated to 10 lines]"
    return "\n".join(lines)

def analyze_similar_failures(job_id, failing_module, test_name, current_incident, current_version, current_arch):
    
    def get_setting(job_data, key, default="None"):
        return str(job_data.get('settings', {}).get(key, default))

    def target_module_failed(job_data):
        for mod in job_data.get('modules', []):
            if mod.get('name') == failing_module and mod.get('result') in ['failed', 'died', 'incomplete']:
                return True
        return False

    # Get last 150 failed jobs & 50 passed jobs for this TEST
    try:
        failed_jobs_raw = requests.get(
            f"{OPENQA_BASE_URL}/api/v1/jobs", 
            params={"test": test_name, "result": "failed", "limit": 150},
            verify=False, timeout=API_TIMEOUT
        ).json().get('jobs', [])
        
        passed_jobs_raw = requests.get(
            f"{OPENQA_BASE_URL}/api/v1/jobs", 
            params={"test": test_name, "result": "passed", "limit": 50},
            verify=False, timeout=API_TIMEOUT
        ).json().get('jobs', [])
    except Exception as e:
        return {"error": f"API query failed: {str(e)}"}

    # Get jobs (all results) specifically for this INCIDENT_ID + TEST
    incident_jobs = []
    if current_incident and current_incident.lower() != 'none':
        try:
            incident_jobs = requests.get(
                f"{OPENQA_BASE_URL}/api/v1/jobs", 
                params={"test": test_name, "job_setting": f"INCIDENT_ID={current_incident}", "limit": 100},
                verify=False, timeout=API_TIMEOUT
            ).json().get('jobs', [])
        except Exception:
            pass 

    # Filter out current job
    failed_jobs_raw = [j for j in failed_jobs_raw if str(j['id']) != str(job_id)]
    passed_jobs_raw = [j for j in passed_jobs_raw if str(j['id']) != str(job_id)]
    incident_jobs = [j for j in incident_jobs if str(j['id']) != str(job_id)]
    
    matching_fails = [j for j in failed_jobs_raw if target_module_failed(j)]
    fail_incidents = Counter([get_setting(j, 'INCIDENT_ID') for j in matching_fails])
    fail_versions = Counter([get_setting(j, 'VERSION') for j in matching_fails])
    fail_arches = Counter([get_setting(j, 'ARCH') for j in matching_fails])

    inc_passed = [j for j in incident_jobs if j.get('result') == 'passed']
    inc_failed = [j for j in incident_jobs if j.get('result') == 'failed']
    
    # Get 3 newest AND 3 oldest matching fails
    errors_in_jobs_failing_the_same_module = {}
    
    jobs_to_detail_dict = {str(j['id']): j for j in matching_fails[:3]}
    if len(matching_fails) > 3:
        jobs_to_detail_dict.update({str(j['id']): j for j in matching_fails[-3:]})
    
    for f_job_id, f_job in jobs_to_detail_dict.items():
        try:
            details_url = f"{OPENQA_BASE_URL}/api/v1/jobs/{f_job_id}/details"
            details_resp = requests.get(details_url, verify=False, timeout=API_TIMEOUT)
            details_resp.raise_for_status()
            testresults = details_resp.json().get('job', {}).get('testresults', [])
            
            job_failed_modules = {}
            
            for mod in testresults:
                if mod.get('result') in ['fail', 'failed', 'died']:
                    mod_name = mod.get('name', 'Unknown_Module')
                    extracted_texts = []
                    
                    if mod.get('text_data'):
                        extracted_texts.append(extract_top_10(mod.get('text_data')))
                    
                    for step in mod.get('details', []):
                        if step.get('result') in ['fail', 'failed', 'died'] and step.get('text_data'):
                            extracted_texts.append(extract_top_10(step.get('text_data')))
                    
                    if extracted_texts:
                        job_failed_modules[mod_name] = sanitize_text("\n---\n".join(extracted_texts))
                    else:
                        job_failed_modules[mod_name] = "No text_data found in this module's details."
            
            errors_in_jobs_failing_the_same_module[f_job_id] = job_failed_modules
            
        except Exception as e:
            errors_in_jobs_failing_the_same_module[f_job_id] = {
                "error": f"Failed fetching details: {str(e)}"
            }

    if inc_passed:
        passed_incident_output = dict(Counter([f"{get_setting(j, 'ARCH')} + {get_setting(j, 'VERSION')}" for j in inc_passed]))
    else:
        passed_incident_output = "No passing jobs were found for this TEST and incident"

    if inc_failed:
        failed_incident_output = dict(Counter([f"{get_setting(j, 'ARCH')} + {get_setting(j, 'VERSION')}" for j in inc_failed]))
    else:
        failed_incident_output = "No failing jobs were found for this TEST and incident"

    # Hints for the agent
    insights = []
    if not matching_fails:
        insights.append(f"Module did NOT fail in the last 150 failed runs of this test. This might be a brand new regression, OR past failures on other incidents are simply too far back to appear in the limit.")
    else:
        if len(fail_incidents) > 1 or (len(fail_incidents) == 1 and 'None' in fail_incidents and current_incident.lower() != 'none'):
            insights.append("CRITICAL: General failure occurs across DIFFERENT incident IDs (or both with/without incidents). Likely INFRASTRUCTURE, TEST FLAKE, or PRODUCT REGRESSION. NOT an update regression.")
        elif len(fail_incidents) == 1 and list(fail_incidents.keys())[0] == current_incident and current_incident.lower() != 'none':
            if len(matching_fails) > 2:
                insights.append(f"CRITICAL: In the general test history (found {len(matching_fails)} times), this failure is ONLY seen on jobs with the EXACT SAME incident ID.")
            else:
                insights.append(f"WARNING: This failure was only seen on the current incident, BUT it only appeared {len(matching_fails)} time(s) in the general history. Because the sample size is so small, failures on other incidents might have been pushed out of the job limit. Do not blindly assume an update regression.")

    if current_incident and current_incident.lower() != 'none':
        if len(inc_passed) > 0:
            insights.append(f"NOTE: This specific update (Incident {current_incident}) PASSED {len(inc_passed)} times in other runs. Review the 'passing_jobs_with_specified_TEST+INCIDENT' matrix. If it passes on the failing ARCH/VERSION, it severely lowers the probability of an update regression.")
        elif len(inc_failed) > 0 and len(inc_passed) == 0:
            insights.append(f"CRITICAL: This specific update (Incident {current_incident}) has a 100% failure rate across {len(inc_failed)} recent runs for this test. High probability of Update Regression.")

    report = {
        "failing_jobs_with_specified_TEST": {
            "total_module_failures_in_last_150": len(matching_fails),
            "failure_distribution": {
                "by_incident": dict(fail_incidents),
                "by_version": dict(fail_versions),
                "by_arch": dict(fail_arches)
            }
        },
        "passing_jobs_with_specified_TEST": {
            "total_passes_in_last_50": len(passed_jobs_raw),
            "pass_distribution": {
                "by_incident": dict(Counter([get_setting(j, 'INCIDENT_ID') for j in passed_jobs_raw])),
                "by_version": dict(Counter([get_setting(j, 'VERSION') for j in passed_jobs_raw])),
                "by_arch": dict(Counter([get_setting(j, 'ARCH') for j in passed_jobs_raw]))
            }
        },
        "errors_in_jobs_failing_the_same_module": errors_in_jobs_failing_the_same_module,
        "insights": insights
    }

    if current_incident and current_incident.lower() != 'none':
        report["failing_jobs_with_specified_TEST+INCIDENT"] = failed_incident_output
        report["passing_jobs_with_specified_TEST+INCIDENT"] = passed_incident_output

    return report

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Find similar openQA failures.")
    parser.add_argument("--job", required=True, help="Current failing job ID")
    parser.add_argument("--module", required=True, help="Failing module name")
    parser.add_argument("--test", required=True, help="TEST scenario name")
    parser.add_argument("--incident", default="None", help="INCIDENT_ID (if any)")
    parser.add_argument("--version", default="Unknown", help="VERSION of the failing job")
    parser.add_argument("--arch", default="Unknown", help="ARCH of the failing job")
    
    args = parser.parse_args()
    
    print(json.dumps(analyze_similar_failures(
        job_id=args.job,
        failing_module=args.module,
        test_name=args.test,
        current_incident=args.incident,
        current_version=args.version,
        current_arch=args.arch
    ), indent=2))
