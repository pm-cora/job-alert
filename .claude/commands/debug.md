GitHub Actions 워크플로우를 실행하고 결과를 검증하세요. 아래 순서대로 진행합니다.

1. PowerShell로 워크플로우를 실행하세요:
   ```
   $env:PATH = $env:PATH + ";C:\Program Files\GitHub CLI"
   gh workflow run daily_job_alert.yml --repo pm-cora/job-alert
   ```

2. 반환된 run ID로 완료될 때까지 watch하세요:
   ```
   gh run watch <run_id> --repo pm-cora/job-alert
   ```

3. 완료되면 로그에서 공고 목록을 추출하세요:
   ```
   gh run view <run_id> --repo pm-cora/job-alert --log 2>&1 | Select-String "총|필터|  \d+\."
   ```

4. 추출한 공고 목록을 아래 기준으로 전수 검증하세요:

   **직무 조건**: 제목에 Product Manager / Program Manager / Project Manager / Product Lead / Product Operations 중 하나가 포함되어야 함

   **위치 조건**:
   - Remote인 경우: Canada 명시 또는 국가 미지정이어야 함. "Remote, US" / "Remote US" / UK / Mexico 등 비캐나다 국가가 명시된 경우 ❌
   - On-site/Hybrid인 경우: Vancouver 광역권(Vancouver, Burnaby, Richmond, Surrey, North Vancouver 등)이어야 함

   **날짜 조건**: 날짜가 있는 경우 오늘 기준 7일 이내여야 함. 날짜 없는 경우 "within 7 days (by Google)" — 설계상 허용

5. 결과를 표로 정리해서 보고하세요:
   - ✅ 정상 공고 수
   - ❌ 문제 공고 목록 (번호, 제목, 회사, 위치, 문제 이유)
   - ⚠️ 애매한 공고 (국가 미지정 Remote 등)
