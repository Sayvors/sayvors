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

    # Lane for each job type
    LANE_MAP: dict["JobType", JobLane] = {
        meta_send_reply: JobLane.realtime,
        meta_send_template: JobLane.realtime,
        post_publish: JobLane.publishing,
        post_delete: JobLane.publishing,
        media_publish: JobLane.publishing,
        media_process: JobLane.media,
        databank_ingest: JobLane.bulk,
        scrape_url: JobLane.bulk,
        stt_job: JobLane.bulk,
        tts_job: JobLane.bulk,
    }

    @classmethod
    def lane_for(cls, job_type: "JobType") -> JobLane:
        return cls.LANE_MAP[job_type]


# JOB_TYPES is the closed registry validated server-side on submit.
JOB_TYPES = [jt.value for jt in JobType]
