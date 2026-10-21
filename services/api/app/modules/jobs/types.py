"""Job type registry and lane definitions.

Single source of truth for all job types. Each job type maps to exactly one
lane, and handlers live in `app/modules/jobs/handlers/<job_type>.py`.
"""

from enum import Enum


class JobLane(str, Enum):
    realtime = "realtime"
    publishing = "publishing"
    media = "media"
    bulk = "bulk"


class JobType(str, Enum):
    # ── realtime lane ── customer-facing, latency-critical
    meta_send_reply = "meta.send_reply"      # WhatsApp / IG / FB AI reply
    meta_send_template = "meta.send_template"  # template message send

    # ── publishing lane ── provider-quota-bound
    post_publish = "post.publish"            # Google Business Profile post
    post_delete = "post.delete"              # take a published post down on schedule
    media_publish = "media.publish"          # Google media upload

    # ── media lane ── memory-bound image processing
    media_process = "media.process"          # image resize / convert

    # ── bulk lane ── best-effort, yielding
    databank_ingest = "databank.ingest"      # RAG document ingest
    scrape_url = "scrape.url"                # URL scraping
    stt_job = "stt.job"                      # speech-to-text
    tts_job = "tts.job"                      # text-to-speech

    @classmethod
    def lane_for(cls, job_type: "JobType") -> JobLane:
        return _LANE_MAP[job_type]


# Module-level map, not an enum attribute: a dict assigned inside an Enum
# body becomes a member (and a classmethod that indexes it would look up the
# member, not the map). Keeping it here makes the mapping data, not a job type.
_LANE_MAP: dict[JobType, JobLane] = {
    JobType.meta_send_reply: JobLane.realtime,
    JobType.meta_send_template: JobLane.realtime,
    JobType.post_publish: JobLane.publishing,
    JobType.post_delete: JobLane.publishing,
    JobType.media_publish: JobLane.publishing,
    JobType.media_process: JobLane.media,
    JobType.databank_ingest: JobLane.bulk,
    JobType.scrape_url: JobLane.bulk,
    JobType.stt_job: JobLane.bulk,
    JobType.tts_job: JobLane.bulk,
}


# JOB_TYPES is the closed registry validated server-side on submit.
JOB_TYPES = [jt.value for jt in JobType]
