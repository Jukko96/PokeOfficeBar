# PokeOfficeBar

Windows에서 일하는 동안 바탕화면의 작은 친구를 키우는 앱입니다. 화면이 잠겨 있지 않을 때 1분에 1포인트를 적립하고, 화면을 잠그거나 PC가 절전 상태에 들어가면 적립을 멈춥니다.

## Windows에서 바로 실행

**[PokeOfficeBar.exe 다운로드](https://github.com/Jukko96/PokeOfficeBar/releases/latest/download/PokeOfficeBar.exe)**를 눌러 받은 파일을 실행하세요. Windows 10 또는 11의 64비트 환경을 지원하며 Python 설치는 필요 없습니다.

> [!IMPORTANT]
> **‘Windows의 PC 보호’ 창이 뜨면**
>
> 공개 EXE에 아직 코드 서명이 없어 Microsoft Defender SmartScreen 경고가 뜰 수 있습니다. **현재 이 경고를 줄이기 위해 코드 서명 적용을 준비 중입니다.**
>
> 1. 위 다운로드 버튼이나 [공식 GitHub Releases](https://github.com/Jukko96/PokeOfficeBar/releases)에서 받은 `PokeOfficeBar.exe`인지 확인하세요.
> 2. 경고 창에서 **추가 정보**를 누르세요.
> 3. 공식 파일이라는 것을 확인했고 **실행** 버튼이 표시되면 **실행**을 누르세요. 출처가 확실하지 않으면 **실행 안 함**을 선택하세요.

처음에는 도감과 이미지를 가져오기 위해 인터넷에 연결해 주세요. PokeTokenBar를 실행 중이라면 트레이에서 종료한 뒤 열면 기존 회사원 모드 세이브를 이어서 사용할 수 있습니다.

앱을 열 때 GitHub의 최신 정식 버전을 확인합니다. 새 버전이 있으면 실행 파일을 내려받고 검증한 뒤 자동으로 교체하고 다시 엽니다. 자동 업데이트를 완료하지 못하면 홈의 **다운로드** 버튼으로 릴리스 페이지를 열 수 있습니다. 이전 버전에서 이 기능을 처음 사용하려면 이 버전의 EXE로 한 번 교체해 주세요.

## 패치 노트

### v0.1.5

- 홈에서 현재 설치된 버전의 패치 노트를 볼 수 있습니다.
- 향로 방문을 적게, 보통, 많이, 우르르 중 선택할 수 있습니다. 기본인 보통은 최대 10마리, 우르르는 짧은 간격으로 최대 30마리가 찾아옵니다.
- README 상단에 Windows SmartScreen 경고가 나왔을 때의 실행 안내를 추가했습니다.

## 주요 기능

- **육성** · 기존 PokeTokenBar의 1~5세대 포켓몬 649종과 일반·이로치 수집을 지원합니다.
- **바탕화면** · 트레이나 포켓몬을 우클릭해 화면 전체 또는 작업 표시줄 위를 걷게 할 수 있습니다.
- **선물과 향로** · 가져온 선물을 직접 받고, 향로로 졸업생을 부릅니다. 변장한 메타몽은 가끔 본모습을 드러내며, 방문 중에 발견하면 포인트를 받습니다.
- **가방** · 가지고 있는 아이템을 상점가의 절반에 팝니다. 수량을 고르거나 전부를 선택한 뒤 받을 포인트를 확인할 수 있습니다.
- **화분과 탐험대** · 화분을 가꾸고, 졸업생을 다섯 목적지에 보내 돌아오면 보상을 받습니다.

## 소스에서 실행

Windows 10 또는 11과 Tkinter를 포함한 64비트 Python 3.11 이상이 필요합니다. 프로젝트 폴더에서 PowerShell을 열고 실행하세요.

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\pythonw.exe run.pyw
```

창을 닫으면 트레이에서 계속 실행됩니다. 프로그램을 종료하려면 트레이 아이콘을 우클릭해 **종료**를 선택하세요.

회사원 모드 진행 상황은 기존 PokeTokenBar와 같은 `%LOCALAPPDATA%\PokeTokenBarWin\office-save.json`에 저장합니다. 두 앱은 동시에 같은 세이브를 열지 않도록 잠금을 공유합니다. PokeOfficeBar 설정은 `%LOCALAPPDATA%\PokeOfficeBar\config.json`에 저장합니다.

도감과 이미지는 동봉된 팩, 기존 `PokeTokenBarWin\cache`, PokéAPI 순서로 찾습니다. 캐시에 없는 이미지와 도감 데이터는 백그라운드에서 가져와 캐시에 저장합니다.

**Windows 자동 시작**은 기본으로 켜져 있습니다. 앱을 한 번 열면 다음 Windows 로그인부터 트레이에서 자동으로 시작됩니다. 끄려면 설정에서 **Windows 로그인 시 자동 시작**의 체크를 해제하고 저장하세요. 실행 파일이나 프로젝트 폴더를 옮겼다면 새 위치에서 한 번 열어 주세요.

**근무 카운트다운**은 설정, 데스크톱 포켓몬 또는 트레이의 우클릭 메뉴에서 켜거나 끌 수 있습니다. 기본 시각은 출근 09:00, 식사 시작 12:00, 다음 근무 시작 13:00, 퇴근 18:00입니다. 포켓몬 머리 위에서 식사까지, 다음 근무까지, 퇴근까지 남은 시간을 순서대로 보여줍니다. 퇴근 시각에는 1분간 ‘퇴근!’을 표시합니다.

## Windows 실행 파일 만들기

```powershell
.\.venv\Scripts\python.exe -m pip install pyinstaller pefile
.\.venv\Scripts\python.exe build.py
```

완성된 실행 파일은 `dist/PokeOfficeBar.exe`에 생성됩니다. 배포할 때는 라이선스 고지를 함께 보존하세요.

새 버전을 공개할 때는 위 패치 노트에 `### v버전` 제목과 변경 사항을 목록으로 작성합니다. 앱 홈은 빌드에 포함된 README에서 현재 버전의 내용을 읽습니다. 해당 버전의 소스에서 EXE를 다시 빌드하고, 같은 버전의 GitHub 릴리스에 `PokeOfficeBar.exe`로 첨부합니다. 게시 후 README의 다운로드 버튼이 새 EXE로 연결되는지 확인합니다.

로컬 이미지 팩이 있다면 개인용 오프라인 빌드에 `build.py --pokemon-data 경로`로 넣을 수 있습니다.

## 출처 및 라이선스

[PokeTokenBar for Windows](https://github.com/NMHK-134711/PokeTokenBar-for-Windows)를 기반으로 했습니다. Windows판의 출발점은 [chattymin/PokeTokenBar](https://github.com/chattymin/PokeTokenBar)의 아이디어입니다. 기반 코드의 MIT 저작권 고지와 라이선스 전문은 [LICENSE](LICENSE)에 있습니다.

도감과 스프라이트의 출처는 [PokéAPI](https://pokeapi.co/)입니다. 향로 아이콘은 [Pokémon GO 공식 자료](https://www.pokemon.com/static-assets/content-assets/cms2/img/video-games/_tiles/pokemon-go/2025/11/07/inline/05.png)에서 가져옵니다. 포켓몬 이미지와 데이터의 권리는 각 권리자에게 있으며, 기본 소스와 빌드에는 포켓몬 이미지 팩을 넣지 않습니다. 대체 아이콘은 `pokeofficebar/art.py`에서 그립니다. 선물 아이콘과 탐험 배경은 이 프로젝트용으로 생성한 이미지입니다.
