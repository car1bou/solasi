import AppKit

final class UninstallChoiceView: NSStackView {
    private var controls: [String:NSSegmentedControl] = [:]
    var selection: [String:Bool] { controls.mapValues { $0.selectedSegment == 0 } }

    init(selection: [String:Bool]) {
        super.init(frame:NSRect(x:0,y:0,width:380,height:150))
        orientation = .vertical; alignment = .leading; spacing = 12
        var rows: [[NSView]] = []
        for (key,title) in [("documents","필기·문서"),("audio","녹음"),("results","전사·AI 결과")] {
            let label = NSTextField(labelWithString:title)
            label.widthAnchor.constraint(equalToConstant:170).isActive = true
            let control = NSSegmentedControl(labels:["보존","삭제"],trackingMode:.selectOne,target:nil,action:nil)
            control.selectedSegment = selection[key] == false ? 1 : 0
            control.setAccessibilityLabel(title+" 처리")
            controls[key] = control; rows.append([label,control])
        }
        let grid = NSGridView(views:rows); grid.rowSpacing = 12; grid.columnSpacing = 16
        addArrangedSubview(grid)
        let help = NSTextField(wrappingLabelWithString:"보존을 고른 기록은 앱 없이 열 수 있는 파일로 남깁니다. 삭제를 고른 기록은 보존하지 않습니다. 선택을 바꾸면 다시 검증하며, 이미 만든 보존 파일은 유지합니다.")
        help.widthAnchor.constraint(equalToConstant:380).isActive = true
        addArrangedSubview(help)
    }
    required init?(coder: NSCoder) { fatalError("init(coder:) has not been implemented") }
}
