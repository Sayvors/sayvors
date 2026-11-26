==============================================================================
SAYVORS AI PIPELINE - RESPONSE / DIALECT CHECK
==============================================================================
Generated      : 2026-11-17
Pipeline       : review_engine (analyze_review -> generate_response -> validate_response)
Model          : openrouter:openai/gpt-4o-2024-11-20
Settings       : dialect=auto, reply_language=match, rating=5, no business context / databank
Note on setup  : billing reservation + DB log write were skipped (local DB schema is behind
                 a migration: users.vertical_key missing). The response-quality stages - the
                 real language detector, dialect-aware generation and validator - are live.
Note on dialect: the pipeline emits a language label (ar) + confidence, NOT a discrete dialect
                 label. In auto mode the generator is told to MIRROR the review's dialect
                 (fallback: Saudi/Najdi-Gulf). The DIALECT CHECK line below is a manual audit
                 of the question's dialect vs the dialect the reply actually came out in.

------------------------------------------------------------------------------
[01] QUESTION: وش عندكم عشا يسد الجوع بس ما يكون دسم؟ وتراني ما آكل لحم، الدجاج عادي.
     PIPELINE REPLY: أهلًا! بالنسبة لسؤالك عن خيارات عشاء غير دسمة وبدون لحم، نعتذر ما عندنا التفاصيل هنا. الأفضل تزورنا أو تتواصل معنا مباشرة عشان نعطيك الخيارات المناسبة لك. حياك!
     DETECTION : language=ar (detector=ar, confidence=0.95, script=arabic, rtl=True) | intent=question | question=True | sentiment=positive/indifference | urgency=low | issue_type=None
     DIALECT CHECK: question=Saudi/Gulf (Najdi) | reply=Saudi/Gulf | MATCH
                    وش/تراني/عادي -> عشان/حياك/تزورنا
     VALIDATION: PASS  | latency=4.9s
------------------------------------------------------------------------------
[02] QUESTION: أبي غرفة ليلتين، معي المدام وبنتين صغار، وش أوفر لنا: جناح ولا غرفتين بينها باب؟
     PIPELINE REPLY: حياك الله! بالنسبة لاختيار الجناح أو الغرفتين، يعتمد على احتياجكم وراحتكم. ما عندي التفاصيل الآن، لكن تقدر تتواصل مع فريقنا مباشرة عشان يعطونك أفضل اقتراح يناسبك.
     DETECTION : language=ar (detector=ar, confidence=0.95, script=arabic, rtl=True) | intent=question | question=True | sentiment=very_positive/indifference | urgency=medium | issue_type=None
     DIALECT CHECK: question=Saudi/Gulf | reply=Saudi/Gulf | MATCH
                    أبي/المدام/وش -> حياك الله/تقدر/عشان
     VALIDATION: PASS  | latency=3.6s
------------------------------------------------------------------------------
[03] QUESTION: انخصم المبلغ من حسابي، والمحل يقول العملية ما مشت، الحين أراجعكم ولا أراجعه؟
     PIPELINE REPLY: نأسف على المشكلة اللي صارت. الأفضل تراجعين المحل مباشرة، وإذا ما انحلت المشكلة تواصلينا ونساعدك.
     DETECTION : language=ar (detector=ar, confidence=0.95, script=arabic, rtl=True) | intent=question | question=True | sentiment=neutral/indifference | urgency=medium | issue_type=billing
     DIALECT CHECK: question=Saudi/Gulf | reply=Saudi/Gulf | MATCH
                    انخصم/المحل/ما مشت/الحين -> نأسف/تراجعين/تواصلينا
     VALIDATION: PASS  | latency=4.3s
------------------------------------------------------------------------------
[04] QUESTION: أبي جوال لأبوي، ما تهمه الكاميرا كثر ما يهمه الخط يكون واضح والبطارية تطوّل، وش عندكم؟
     PIPELINE REPLY: حياك الله، بالنسبة للجوال اللي يناسب احتياج والدك من حيث وضوح الخط وعمر البطارية، نرجو منك التواصل معنا مباشرة عشان نعطيك التفاصيل الأدق ونساعدك تختار الأنسب.
     DETECTION : language=ar (detector=ar, confidence=0.95, script=arabic, rtl=True) | intent=question | question=True | sentiment=very_positive/indifference | urgency=low | issue_type=None
     DIALECT CHECK: question=Saudi/Gulf | reply=Saudi/Gulf | MATCH
                    أبي/وش -> حياك الله/عشان/نرجو
     VALIDATION: PASS  | latency=3.6s
------------------------------------------------------------------------------
[05] QUESTION: وشوله تحسبون التوصيل مرتين وأنا طالب من نفس الفرع؟ الطلبين بيجون سوا وإلا كل واحد لحاله؟
     PIPELINE REPLY: نفهم استفسارك بخصوص احتساب التوصيل مرتين مع أن الطلبين من نفس الفرع. ما عندنا التفاصيل الدقيقة هنا، لكن فريقنا بيتابع الموضوع ويوضح لك. نرجو التواصل معنا مباشرة لمساعدتك أكثر.
     DETECTION : language=ar (detector=ar, confidence=0.95, script=arabic, rtl=True) | intent=question,complaint | question=True | sentiment=neutral/indifference | urgency=medium | issue_type=billing
     DIALECT CHECK: question=Saudi/Gulf | reply=Saudi/Gulf | MATCH
                    وشوله/بيجون/لحاله -> نفهم/بيتابع/نرجو
     VALIDATION: PASS  | latency=3.8s
------------------------------------------------------------------------------
[06] QUESTION: أبي نفس هالثوب، مير المقاس اللي قبله، مب اللي أكبر منه، موجود عندكم؟
     PIPELINE REPLY: حياك الله! بالنسبة للثوب اللي طلبتيه، ما عندنا تفاصيل دقيقة هنا. نرجو تزورينا أو تتواصلي مع الفريق عشان يفيدونك أكثر.
     DETECTION : language=ar (detector=ar, confidence=0.95, script=arabic, rtl=True) | intent=question | question=True | sentiment=very_positive/joy | urgency=medium | issue_type=None
     DIALECT CHECK: question=Saudi/Gulf | reply=Saudi/Gulf | MATCH
                    هالثوب/مير/مب -> حياك الله/تزورينا
     VALIDATION: PASS  | latency=4.5s
------------------------------------------------------------------------------
[07] QUESTION: أبغى البرجر من غير بصل، بس الصوص اللي فيه نكهة بصل عادي، تقدروا تسوّوه كذا؟
     PIPELINE REPLY: أهلًا! بالنسبة للبرجر بدون بصل مع بقاء الصوص بنكهة البصل، ما عندنا تفاصيل أكيدة الآن. نرجو التواصل معنا مباشرة عشان نتأكد ونساعدك.
     DETECTION : language=ar (detector=ar, confidence=0.95, script=arabic, rtl=True) | intent=question | question=True | sentiment=very_positive/indifference | urgency=low | issue_type=None
     DIALECT CHECK: question=Saudi/Gulf | reply=Saudi/Gulf | MATCH
                    أبغى/من غير بصل -> أهلًا/عشان. NOTE: validation FAILED
     VALIDATION: FAIL ['Unaddressed complaint facts: complaint subject (البرجر)'] | latency=2.6s
------------------------------------------------------------------------------
[08] QUESTION: دحين لو وصلتكم بعد نص الليل، أحجز بتاريخ اليوم اللي طلعت فيه ولا اليوم اللي أوصل فيه؟
     PIPELINE REPLY: أهلًا، بالنسبة للحجز بعد نص الليل، الأفضل تتواصل معنا مباشرة عشان نعطيك التفاصيل الدقيقة ونساعدك. حياك بأي وقت!
     DETECTION : language=ar (detector=ar, confidence=0.95, script=arabic, rtl=True) | intent=question | question=True | sentiment=neutral/indifference | urgency=low | issue_type=None
     DIALECT CHECK: question=Saudi/Gulf | reply=Saudi/Gulf | MATCH
                    دحين/نص الليل -> أهلًا/عشان/حياك
     VALIDATION: PASS  | latency=3.4s
------------------------------------------------------------------------------
[09] QUESTION: لو سمحتوا، الوالدة ما تقدر توقف كتير، فين أنزّلها عشان تدخل العيادة على طول؟
     PIPELINE REPLY: حياك الله، نفهم إن والدتك تحتاج مكان قريب وسهل الوصول. نرجو التواصل معنا مباشرة عشان نساعدك بمعلومات دقيقة عن أقرب مكان ممكن تنزل فيه.
     DETECTION : language=ar (detector=ar, confidence=0.95, script=arabic, rtl=True) | intent=question | question=True | sentiment=positive/indifference | urgency=medium | issue_type=facility_premises
     DIALECT CHECK: question=Gulf (فين، على طول) | reply=Saudi/Gulf | MATCH
                    فين/أنزّلها -> نفهم/نرجو/عشان
     VALIDATION: PASS  | latency=2.4s
------------------------------------------------------------------------------
[10] QUESTION: عندكم دا المقاس في فرع تاني؟ وإذا موجود، تقدروا تحجزوه لي لين أجي بكرة؟
     PIPELINE REPLY: أهلاً، للأسف ما عندي تفاصيل أكيدة عن توفر المقاس في الفروع الثانية أو إمكانية الحجز. الأفضل تتواصلين مباشرة مع الفرع للتأكد والحجز إذا ممكن. حياك الله!
     DETECTION : language=ar (detector=ar, confidence=0.95, script=arabic, rtl=True) | intent=question | question=True | sentiment=very_positive/indifference | urgency=low | issue_type=None
     DIALECT CHECK: question=Egyptian/Gulf mix (دا، تاني، لين، بكرة) | reply=Saudi/Gulf | PARTIAL
                    Gulf reply; Egyptian دا/تاني not mirrored
     VALIDATION: PASS  | latency=3.1s
------------------------------------------------------------------------------
[11] QUESTION: أبي الطلب سفري، بس لا تجهزونه الحين، باقي لي نص ساعة وأوصلكم، متى أطلب منكم تبدون فيه؟
     PIPELINE REPLY: حياك الله! الأفضل تتواصل معنا مباشرة قبل وصولك بنص ساعة عشان نجهز الطلب بوقته. ننتظرك!
     DETECTION : language=ar (detector=ar, confidence=0.95, script=arabic, rtl=True) | intent=question | question=True | sentiment=positive/indifference | urgency=low | issue_type=None
     DIALECT CHECK: question=Saudi/Gulf | reply=Saudi/Gulf | MATCH
                    أبي/سفري/الحين -> حياك الله/عشان/ننتظرك
     VALIDATION: PASS  | latency=2.9s
------------------------------------------------------------------------------
[12] QUESTION: حوّلت لخويي من أمس وللحين ما جاه شي، والمبلغ طالع من عندي، شالسالفة؟
     PIPELINE REPLY: نأسف لسماع إن التحويل ما وصل لخويّك. يُفضل تتواصل معنا على الخاص مع تفاصيل العملية عشان نتابع الموضوع ونتأكد من الحل.
     DETECTION : language=ar (detector=ar, confidence=0.95, script=arabic, rtl=True) | intent=question,complaint | question=True | sentiment=negative/frustration | urgency=high | issue_type=billing
     DIALECT CHECK: question=Saudi/Gulf | reply=Saudi/Gulf | MATCH
                    خويي/شالسالفة -> خويّك/على الخاص. NOTE: validation FAILED
     VALIDATION: FAIL ['Unaddressed complaint facts: complaint subject (billing)'] | latency=2.5s
------------------------------------------------------------------------------
[13] QUESTION: أبي تمر حق هدية، مب حق استخدام البيت، وش عندكم زين وكم يطلع الكرتون مع التغليف؟
     PIPELINE REPLY: حياك الله! بالنسبة للتمر والهدايا مع التغليف، الأفضل تتواصل معنا مباشرة عشان نعطيك التفاصيل الدقيقة عن الأنواع والأسعار. ننتظرك ونتشرف بخدمتك!
     DETECTION : language=ar (detector=ar, confidence=0.95, script=arabic, rtl=True) | intent=question | question=True | sentiment=very_positive/indifference | urgency=low | issue_type=None
     DIALECT CHECK: question=Saudi/Gulf | reply=Saudi/Gulf | MATCH
                    أبي/حق/وش -> حياك الله/عشان
     VALIDATION: PASS  | latency=3.3s
------------------------------------------------------------------------------
[14] QUESTION: يا بعد حيي، حنا سبعة ومعنا بزرين، يكفينا نص ذبيحة وإلا نزيد عليه؟
     PIPELINE REPLY: حياكم الله، بالنسبة لنص الذبيحة يكفي أو لا يعتمد على شهيتكم وكمية الأكل المطلوبة. ننصحكم تتواصلون معنا مباشرة عشان نعطيكم التفاصيل الأدق ونساعدكم في الطلب.
     DETECTION : language=ar (detector=ar, confidence=0.95, script=arabic, rtl=True) | intent=question | question=True | sentiment=very_positive/joy | urgency=low | issue_type=None
     DIALECT CHECK: question=Saudi/Gulf | reply=Saudi/Gulf | MATCH
                    يا بعد حيي/حنا/بزرين/وإلا -> حياكم/ننصحكم
     VALIDATION: PASS  | latency=2.7s
------------------------------------------------------------------------------
[15] QUESTION: ودنا نسكن عندكم، بس معنا شايب نومه خفيف، عندكم غرف بعيدة عن المصعد وصجة الشارع؟
     PIPELINE REPLY: حياكم الله، سؤالكم مهم. ما عندنا التفاصيل الدقيقة هنا عن الغرف البعيدة عن المصعد أو صجة الشارع، لكن تقدرون تتواصلون معنا مباشرة عشان نعطيكم الإجابة الأكيدة ونساعدكم.
     DETECTION : language=ar (detector=ar, confidence=0.95, script=arabic, rtl=True) | intent=question | question=True | sentiment=positive/indifference | urgency=low | issue_type=facility_premises
     DIALECT CHECK: question=Saudi/Gulf | reply=Saudi/Gulf | MATCH
                    ودنا/شايب/صجة -> حياكم/تقدرون/عشان
     VALIDATION: PASS  | latency=2.8s
------------------------------------------------------------------------------
[16] QUESTION: وش عندكم من أكل الديرة؟ نبي عريكة، بس العسل والسمن كل واحد لحاله، تضبطونها لنا؟
     PIPELINE REPLY: حياك الله! بالنسبة للعريكة والعسل والسمن كل واحد لحاله، للأسف ما عندي التفاصيل الآن. تقدر تتواصل معنا مباشرة ونعطيك المعلومات الدقيقة.
     DETECTION : language=ar (detector=ar, confidence=0.95, script=arabic, rtl=True) | intent=question | question=True | sentiment=very_positive/joy | urgency=low | issue_type=None
     DIALECT CHECK: question=Saudi/Gulf | reply=Saudi/Gulf | MATCH
                    أكل الديرة/عريكة -> حياك الله/عشان
     VALIDATION: PASS  | latency=3.3s
------------------------------------------------------------------------------
[17] QUESTION: الموتر ما به شي وهو بارد، لا مشيت به شوي قام ينتّع، أفحصه عندكم وإلا أودّيه كهربائي؟
     PIPELINE REPLY: حياك الله. بالنسبة للمشكلة اللي ذكرتها في الموتر، الأفضل تمرنا عشان نفحصه ونتأكد. إذا تبي تفاصيل أكثر، تواصل معنا ونعطيك معلومات دقيقة.
     DETECTION : language=ar (detector=ar, confidence=0.95, script=arabic, rtl=True) | intent=question | question=True | sentiment=neutral/indifference | urgency=medium | issue_type=technical_issue
     DIALECT CHECK: question=Saudi/Gulf | reply=Saudi/Gulf | MATCH
                    الموتر/ينتّع/أفحصه -> حياك الله/تمرنا/إذا تبي
     VALIDATION: PASS  | latency=2.8s
------------------------------------------------------------------------------
[18] QUESTION: شنو عندكم قهوة مو مُرّة وايد؟ وأبيها بحليب خالي لاكتوز، مو خالي دسم، عندكم؟
     PIPELINE REPLY: أهلاً! بالنسبة للقهوة اللي مو مُرّة وايد وبحليب خالي لاكتوز، مو خالي دسم، بنراجع فريقنا ونتأكد إذا متوفرة. نرجو تزورينا أو تتواصلي معنا عشان نعطيك التفاصيل الدقيقة.
     DETECTION : language=ar (detector=ar, confidence=0.95, script=arabic, rtl=True) | intent=question | question=True | sentiment=positive/indifference | urgency=low | issue_type=None
     DIALECT CHECK: question=Saudi/Gulf | reply=Saudi/Gulf | MATCH
                    شنو/وايد/مو -> مو مُرّة وايد (mirrored)
     VALIDATION: PASS  | latency=3.1s
------------------------------------------------------------------------------
[19] QUESTION: أبغي أحجز عندكم الويكند، وياي ياهل عمره سنتين، تحسبون له فطور بروحه ولا داخل معانا؟
     PIPELINE REPLY: حياك الله! بالنسبة لحجز نهاية الأسبوع وسؤال الفطور للطفل، ما عندنا التفاصيل هنا. نرجو تتواصل معنا مباشرة عشان نعطيك الإجابة الدقيقة.
     DETECTION : language=ar (detector=ar, confidence=0.95, script=arabic, rtl=True) | intent=question | question=True | sentiment=very_positive/indifference | urgency=medium | issue_type=general_complaint
     DIALECT CHECK: question=Saudi/Gulf | reply=Saudi/Gulf | MATCH
                    أبغي/الويكند/ياي -> حياك الله/نرجو
     VALIDATION: PASS  | latency=2.7s
------------------------------------------------------------------------------
[20] QUESTION: يصير آخذ الجهاز من الفرع وأقسّط من الموقع، لو لازم الطلب كله أونلاين؟
     PIPELINE REPLY: حياك الله! بالنسبة لسؤالك عن أخذ الجهاز من الفرع والتقسيط عبر الموقع، ما عندنا التفاصيل الدقيقة هنا. الأفضل تتواصل معنا مباشرة عشان نعطيك المعلومات الصحيحة. ننتظرك!
     DETECTION : language=ar (detector=ar, confidence=0.95, script=arabic, rtl=True) | intent=question | question=True | sentiment=neutral/indifference | urgency=low | issue_type=general_complaint
     DIALECT CHECK: question=Saudi/Gulf | reply=Saudi/Gulf | MATCH
                    يصير/أقسّط -> حياك الله/عشان/ننتظرك
     VALIDATION: PASS  | latency=2.4s
------------------------------------------------------------------------------
[21] QUESTION: هو العرض ده على الاتنين بيتزا بأي حجم، ولا الكبيرة بس؟ ولو شلت الجبنة من واحدة السعر بيتغيّر؟
     PIPELINE REPLY: شكرًا لسؤالك. بالنسبة للعرض على البيتزا، ما عندنا التفاصيل الدقيقة هنا. نرجو التواصل مع فريقنا مباشرة للحصول على الإجابة الصحيحة.
     DETECTION : language=ar (detector=ar, confidence=0.95, script=arabic, rtl=True) | intent=question | question=True | sentiment=positive/indifference | urgency=low | issue_type=pricing
     DIALECT CHECK: question=Egyptian (ده، الاتنين) | reply=MSA/Gulf-neutral | MISMATCH
                    شكرًا لسؤالك/نرجو - Egyptian ده/الاتنين not mirrored
     VALIDATION: PASS  | latency=2.5s
------------------------------------------------------------------------------
[22] QUESTION: أنا مش عايز أقفل الحساب، أنا عايز أوقف الكارت اللي ضاع بس، ينفع أعمل ده من الأبلكيشن؟
     PIPELINE REPLY: تقدر توقف الكارت اللي ضاع عن طريق الأبلكيشن، لكن للتأكد من التفاصيل الدقيقة، ننصحك تتواصل معنا مباشرة. حياك بأي وقت!
     DETECTION : language=ar (detector=ar, confidence=0.95, script=arabic, rtl=True) | intent=question | question=True | sentiment=neutral/indifference | urgency=medium | issue_type=general_complaint
     DIALECT CHECK: question=Egyptian (مش عايز، ينفع، ده) | reply=Saudi/Gulf (تقدر، عشان) | MISMATCH
                    ينفع/عايز -> تقدر/عشان/حياك
     VALIDATION: PASS  | latency=2.6s
------------------------------------------------------------------------------
[23] QUESTION: عايز أحجز عند دكتور عظام، بس الكشف يكون بعد ستة، وأي يوم غير الخميس، إيه المتاح؟
     PIPELINE REPLY: مرحبًا، بخصوص حجز موعد مع دكتور عظام بعد الساعة 6 وأي يوم غير الخميس، نرجو التواصل معنا مباشرة لمعرفة المواعيد المتاحة بدقة. نسعد بخدمتك!
     DETECTION : language=ar (detector=ar, confidence=0.95, script=arabic, rtl=True) | intent=question | question=True | sentiment=positive/indifference | urgency=medium | issue_type=None
     DIALECT CHECK: question=Egyptian (عايز، إيه) | reply=MSA/Gulf-neutral | MISMATCH
                    مرحبًا/نرجو/نسعد - Egyptian not mirrored
     VALIDATION: PASS  | latency=2.7s
------------------------------------------------------------------------------
[24] QUESTION: إذا منوصل بكير، فينا نترك الشناتي عندكن ونطلع، ومنرجع وقت تصير الأوضة جاهزة؟
     PIPELINE REPLY: أهلاً، بالنسبة لسؤالك عن ترك الشناتي قبل استلام الغرفة، ما عندي التفاصيل الكاملة هنا. الأفضل تتواصلين معنا مباشرة عشان نعطيك الإجابة الدقيقة. حياك بأي وقت!
     DETECTION : language=ar (detector=ar, confidence=0.95, script=arabic, rtl=True) | intent=question | question=True | sentiment=positive/indifference | urgency=low | issue_type=general_complaint
     DIALECT CHECK: question=Saudi/Gulf | reply=Saudi/Gulf | MATCH
                    منوصل/فينا/الشناتي/الأوضة -> أهلاً/عشان/تتواصلين
     VALIDATION: PASS  | latency=2.5s
------------------------------------------------------------------------------
[25] QUESTION: هالجاكيت طلع ضيّق عليّ، فيني بدّله من فرع غير اللي اشتريته منه؟ الفاتورة معي بس شلت التيكيت.
     PIPELINE REPLY: للأسف ما نقدر نأكد إذا ممكن تبدلين الجاكيت بفرع مختلف، خاصة بعد إزالة التيكيت. الأفضل تزورين أقرب فرع مع الفاتورة وتسألين الفريق هناك، وبيساعدونك بالتفاصيل.
     DETECTION : language=ar (detector=ar, confidence=0.95, script=arabic, rtl=True) | intent=question | question=True | sentiment=neutral/indifference | urgency=medium | issue_type=product_dissatisfaction
     DIALECT CHECK: question=Saudi/Gulf | reply=Saudi/Gulf | MATCH
                    هالجاكيت/فيني/التيكيت -> تبدلين/تزورين/بيساعدونك
     VALIDATION: PASS  | latency=2.7s
------------------------------------------------------------------------------
[26] QUESTION: بدي أطلب منسف لعشرة، بس في اتنين ما بوكلوا لحمة، بتقدروا تعملوا إلهم دجاج بنفس الطلب؟
     PIPELINE REPLY: أهلاً وسهلاً، بالنسبة لطلب المنسف مع تعديل على نوع اللحم لشخصين، نرجو التواصل معنا مباشرة للتأكد من إمكانية تنفيذ الطلب وتفاصيله. حياك الله!
     DETECTION : language=ar (detector=ar, confidence=0.95, script=arabic, rtl=True) | intent=question | question=True | sentiment=very_positive/joy | urgency=medium | issue_type=None
     DIALECT CHECK: question=Levantine (بدي، اتنين، بوكلوا) | reply=Saudi/Gulf | MISMATCH
                    بدي/شو -> أهلاً وسهلاً/حياك الله
     VALIDATION: PASS  | latency=2.6s
------------------------------------------------------------------------------
[27] QUESTION: بدي أستلم دوا أبوي، الوصفة باسمه وهو مش قادر ييجي، شو لازم أجيب معي؟
     PIPELINE REPLY: عشان تستلمي الدوا باسم أبوك، الأفضل تتواصلي معنا مباشرة عشان نعطيك التفاصيل الدقيقة حسب نظامنا. نرحب بمساعدتك بأي وقت!
     DETECTION : language=ar (detector=ar, confidence=0.95, script=arabic, rtl=True) | intent=question | question=True | sentiment=very_positive/indifference | urgency=medium | issue_type=None
     DIALECT CHECK: question=Levantine (بدي، شو، ييجي) | reply=Saudi/Gulf | MISMATCH
                    شو/ييجي -> عشان تستلمي/نرحب
     VALIDATION: PASS  | latency=2.4s
------------------------------------------------------------------------------
[28] QUESTION: هسه إذا أسدّد القسط قبل موعده، ينحسب للقسط الجاي لو بس يقلّل المبلغ اللي بذمّتي؟
     PIPELINE REPLY: هلا! بالنسبة لسؤالك عن تسديد القسط قبل موعده، ما عندي التفاصيل الدقيقة هنا. الأفضل تتواصل مع فريقنا مباشرة عشان يعطونك الإجابة الأكيدة. حاضرين لأي استفسار!
     DETECTION : language=ar (detector=ar, confidence=0.95, script=arabic, rtl=True) | intent=question | question=True | sentiment=neutral/indifference | urgency=low | issue_type=billing
     DIALECT CHECK: question=Iraqi/Gulf (هسه، بذمّتي) | reply=Gulf/Iraqi-leaning | PARTIAL
                    هلا! fits; هسه/بذمّتي not clearly mirrored
     VALIDATION: PASS  | latency=2.5s
------------------------------------------------------------------------------
[29] QUESTION: المكيّف ده بضمان الوكيل ولّا ضمان المحل؟ ولو حصلت ليهو مشكلة، إنتو بتجوا تشيلوه ولّا أجيبو ليكم؟
     PIPELINE REPLY: بالنسبة لضمان المكيّف وطريقة التعامل إذا حصلت مشكلة، ما عندنا التفاصيل الدقيقة هنا. نرجو تتواصل معنا مباشرة عشان نعطيك المعلومات الصحيحة. حياك الله بأي وقت.
     DETECTION : language=ar (detector=ar, confidence=0.95, script=arabic, rtl=True) | intent=question | question=True | sentiment=neutral/indifference | urgency=low | issue_type=general_complaint
     DIALECT CHECK: question=Egyptian/Sudanese (ده، ليهو، إنتو، بتجوا) | reply=Saudi/Gulf | MISMATCH
                    ليهو/إنتو/بتجوا -> حياك الله
     VALIDATION: PASS  | latency=2.9s
------------------------------------------------------------------------------
[30] QUESTION: بغيت نحجز جوج بيوت حدّ بعضياتهم، واحد ليا ولمراتي وواحد للوليدات، واش تقدروا تضمنوا ليا يكونوا متلاصقين؟
     PIPELINE REPLY: أهلاً، فهمت إنك تبغى تحجز بيتين جنب بعض، واحد لك ولمراتك والثاني للأولاد. للأسف ما عندي التفاصيل الدقيقة هنا عن إمكانية تأكيد التلاصق. الأفضل تتواصل مباشرة مع فريق الحجز عشان يعطونك التفاصيل المؤكدة.
     DETECTION : language=ar (detector=ar, confidence=0.4, script=arabic, rtl=True) | intent=question | question=True | sentiment=very_positive/indifference | urgency=medium | issue_type=None
     DIALECT CHECK: question=Moroccan/Maghrebi (بغيت، جوج، واش) | reply=Saudi/Gulf | MISMATCH
                    جوج/واش -> تبغى/عشان. Detector confidence LOW (0.4)
     VALIDATION: PASS  | latency=2.5s

==============================================================================
SUMMARY
==============================================================================
Responses generated        : 30/30 (0 errors)
Language detection         : 30/30 -> ar (Arabic script, RTL)
  low-confidence detection : #30 (0.4); all others 0.95
Question intent detected   : 30/30 (looks_like_question / intent=question)
Dialect audit              : 21 MATCH | 2 PARTIAL | 7 MISMATCH
Validation passed          : 28/30
  failures                 : #7 and #12 - 'Unaddressed complaint facts' (complaint subject)

KEY FINDINGS
1. Language detection is solid: every message is classified as Arabic/RTL with high
   confidence, and every one is recognised as a question (no 'thanks for your review').
2. Dialect mirroring is weak in auto mode. The generator reliably produces natural
   Saudi/Gulf Arabic, but it does NOT mirror non-Gulf dialects. Egyptian (#21-23, #29),
   Levantine (#26-27) and Moroccan (#30) questions all got Saudi/Gulf or MSA replies.
   Moroccan was the worst case: detector confidence dropped to 0.4 and the reply was Gulf.
3. Because no business context/databank was provided, the engine correctly refused to
   invent prices, hours or policies and consistently directed customers to contact the
   business - but this makes most replies generic ('تواصل معنا 직접').
4. Two replies failed validation for leaving a named complaint subject unaddressed
   (#7 burger/onion, #12 billing): the regen loop is active and should be reviewed.

RECOMMENDATION
- Strengthen the auto-dialect prompt (or add an explicit dialect classifier) so that
  clearly Egyptian / Levantine / Iraqi / Maghrebi input is mirrored instead of defaulting
  to Najdi-Gulf; consider a low-confidence dialect -> ask/route path for Maghrebi input.
- Feed real business context/databank facts so question answers stop being generic.
