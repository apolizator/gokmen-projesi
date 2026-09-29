import SwiftUI
import MapKit
import Combine

// --- 1. VERİ MODELLERİ ---
struct TelemetryData: Codable, Sendable {
    let fields: [String: FieldData]?
    let drones: [String: DroneData]?
}

struct FieldData: Codable, Sendable {
    let acre: Double
    let lat: Double
    let lon: Double
    let sprayed_acre: Double
    let owner: String?
    let polygon: [[Double]]?
}

struct DroneData: Codable, Sendable {
    let lat: Double
    let lon: Double
    let state: String
    let battery: Double
    let chemical: Double
    let speed_kmh: Int
}

enum DrawMode {
    case none
    case field
    case droneBase
}

// --- 2. AĞ VE UÇUŞ YÖNETİCİSİ ---
@MainActor
class TelemetryManager: ObservableObject {
    @Published var telemetry: TelemetryData?
    @Published var alertMessage: String = ""
    @Published var showAlert: Bool = false
    
    // KİMLİK SİMÜLATÖRÜ
    @Published var clientId: String = "ÇİFTÇİ_MAC"
    
    // Çizim Araçları
    @Published var drawMode: DrawMode = .none
    @Published var tempCoords: [CLLocationCoordinate2D] = []
    @Published var tempBase: CLLocationCoordinate2D? = nil
    
    // YENİ EV AĞI IP ADRESİN
    let serverIP = "192.168.1.220"
    
    @Published var cameraPosition: MapCameraPosition = .region(MKCoordinateRegion(
        center: CLLocationCoordinate2D(latitude: 39.7495, longitude: 30.4850),
        span: MKCoordinateSpan(latitudeDelta: 0.02, longitudeDelta: 0.02)
    ))
    
    func fetchData() async {
        guard let url = URL(string: "http://\(serverIP):5001/api/telemetry") else { return }
        do {
            let (data, _) = try await URLSession.shared.data(from: url)
            if let decoded = try? JSONDecoder().decode(TelemetryData.self, from: data) {
                self.telemetry = decoded
            }
        } catch { }
    }
    
    // DÖNÜM HESAPLAYICI (Shoelace Teoremi)
    func calculateAcre(coords: [CLLocationCoordinate2D]) -> Double {
        guard coords.count >= 3 else { return 0.0 }
        let lat0 = coords[0].latitude
        let lon0 = coords[0].longitude
        let pts = coords.map { coord -> (Double, Double) in
            let x = (coord.longitude - lon0) * 85500.0
            let y = (coord.latitude - lat0) * 111320.0
            return (x, y)
        }
        var area = 0.0
        for i in 0..<pts.count {
            let j = (i + 1) % pts.count
            area += pts[i].0 * pts[j].1
            area -= pts[j].0 * pts[i].1
        }
        return max(0.01, abs(area) * 0.5 / 1000.0)
    }
    
    // KULEYE DRON (ÜS) KAYIT İSTEĞİ AT
    func requestNewDrone(name: String) {
        guard let base = tempBase else { return }
        guard let url = URL(string: "http://\(serverIP):5001/api/register_drone") else { return }
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        
        let payload: [String: Any] = [
            "drone_name": name, "lat": base.latitude, "lon": base.longitude
        ]
        request.httpBody = try? JSONSerialization.data(withJSONObject: payload)
        
        URLSession.shared.dataTask(with: request) { data, _, _ in
            DispatchQueue.main.async {
                self.alertMessage = "[\(name)] dronu için üs talebi Kuleye iletildi. Onay bekleniyor!"
                self.showAlert = true
                self.drawMode = .none
                self.tempBase = nil
                self.clientId = name
            }
        }.resume()
    }
    
    // KULEYE TARLA ÇİZİM İSTEĞİ AT
    func requestNewField(name: String) {
        guard tempCoords.count >= 3 else { return }
        guard let url = URL(string: "http://\(serverIP):5001/api/request_field") else { return }
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        
        let acre = calculateAcre(coords: tempCoords)
        let poly = tempCoords.map { [$0.latitude, $0.longitude] }
        let avgLat = tempCoords.map { $0.latitude }.reduce(0, +) / Double(tempCoords.count)
        let avgLon = tempCoords.map { $0.longitude }.reduce(0, +) / Double(tempCoords.count)
        
        let payload: [String: Any] = [
            "field_name": name, "lat": avgLat, "lon": avgLon,
            "acre": acre, "owner": self.clientId, "polygon": poly
        ]
        request.httpBody = try? JSONSerialization.data(withJSONObject: payload)
        
        URLSession.shared.dataTask(with: request) { data, _, _ in
            DispatchQueue.main.async {
                self.alertMessage = "[\(name)] tarlası \(self.clientId) adına Kuleye iletildi. Onay Bekleniyor!"
                self.showAlert = true
                self.drawMode = .none
                self.tempCoords = []
            }
        }.resume()
    }
    
    // GÖREV BAŞLATMA
    func startMission(fieldName: String) {
        guard let url = URL(string: "http://\(serverIP):5001/api/start_mission") else { return }
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        let payload = ["field_name": fieldName, "client_id": self.clientId]
        request.httpBody = try? JSONEncoder().encode(payload)
        
        URLSession.shared.dataTask(with: request) { data, response, error in
            if let httpResponse = response as? HTTPURLResponse, httpResponse.statusCode == 403 {
                DispatchQueue.main.async {
                    self.alertMessage = "YETKİ HATASI: Bu tarla size (\(self.clientId)) ait değil!"
                    self.showAlert = true
                }
            } else {
                DispatchQueue.main.async {
                    self.alertMessage = "Görev Başlatıldı! Hedef: \(fieldName)"
                    self.showAlert = true
                }
            }
        }.resume()
    }
}

// --- 3. ANA ARAYÜZ (SEKMELER) ---
struct ContentView: View {
    @StateObject var network = TelemetryManager()
    
    var body: some View {
        TabView {
            RadarTabView(network: network)
                .tabItem { Label("Radar", systemImage: "antenna.radiowaves.left.and.right") }
            
            FieldsTabView(network: network)
                .tabItem { Label("Tarlalarım", systemImage: "leaf.fill") }
            
            OperationsTabView(network: network)
                .tabItem { Label("Operasyon", systemImage: "gauge.with.dots.needle.bottom.100percent") }
        }
        .accentColor(.green)
        .preferredColorScheme(.dark)
        .task {
            while !Task.isCancelled {
                await network.fetchData()
                try? await Task.sleep(nanoseconds: 1_000_000_000)
            }
        }
    }
}

// --- 4. CANLI RADAR VE ÇİZİM EKRANI ---
struct RadarTabView: View {
    @ObservedObject var network: TelemetryManager
    @State private var showingFieldDialog = false
    @State private var showingDroneDialog = false
    @State private var showingIdentityAlert = false
    
    @State private var newNameInput = ""
    
    var body: some View {
        ZStack {
            Color.black.edgesIgnoringSafeArea(.all)
            
            VStack(spacing: 0) {
                // ÜST BAR: KİMLİK MENÜSÜ VE AKSİYONLAR
                HStack {
                    // DİNAMİK KİMLİK SEÇİCİ
                    Menu {
                        if let drones = network.telemetry?.drones {
                            ForEach(Array(drones.keys.sorted()), id: \.self) { droneId in
                                Button(action: { network.clientId = droneId }) {
                                    HStack {
                                        Text(droneId)
                                        if network.clientId == droneId {
                                            Image(systemName: "checkmark")
                                        }
                                    }
                                }
                            }
                        }
                        Divider()
                        Button(action: { showingIdentityAlert = true }) {
                            Label("Manuel Gir / Yeni", systemImage: "pencil")
                        }
                    } label: {
                        Text("👤 \(network.clientId)")
                            .font(.caption).bold()
                            .padding(8).background(Color(white: 0.2)).foregroundColor(.cyan).cornerRadius(8)
                    }
                    
                    Spacer()
                    
                    if network.drawMode == .none {
                        Button(action: { network.drawMode = .droneBase }) {
                            Text("+ ÜS KUR")
                                .font(.caption).bold()
                                .padding(8).background(Color.orange).foregroundColor(.white).cornerRadius(8)
                        }
                        Button(action: { network.drawMode = .field }) {
                            Text("+ TARLA ÇİZ")
                                .font(.caption).bold()
                                .padding(8).background(Color.blue).foregroundColor(.white).cornerRadius(8)
                        }
                    } else {
                        Button(action: {
                            if network.drawMode == .droneBase && network.tempBase != nil { showingDroneDialog = true }
                            else if network.drawMode == .field && network.tempCoords.count >= 3 { showingFieldDialog = true }
                            else { network.alertMessage = "Yetersiz konum verisi!"; network.showAlert = true }
                        }) {
                            Text("✅ GÖNDER")
                                .font(.caption).bold()
                                .padding(8).background(Color.green).foregroundColor(.black).cornerRadius(8)
                        }
                        Button(action: { network.drawMode = .none; network.tempCoords = []; network.tempBase = nil }) {
                            Text("❌ İPTAL")
                                .font(.caption).bold()
                                .padding(8).background(Color.red).foregroundColor(.white).cornerRadius(8)
                        }
                    }
                }.padding(.horizontal).padding(.vertical, 10)
                
                // UYARI METNİ
                if network.drawMode == .field {
                    Text("Tarlanın köşelerini belirlemek için haritaya dokunun.").font(.caption).foregroundColor(.yellow).padding(.bottom, 5)
                } else if network.drawMode == .droneBase {
                    Text("Yeni Dronun kalkış/iniş yapacağı üs konumunu seçin.").font(.caption).foregroundColor(.orange).padding(.bottom, 5)
                }
                
                // HARİTA
                MapReader { proxy in
                    Map(position: $network.cameraPosition) {
                        
                        // 1. KAYITLI TARLALAR
                        if let fields = network.telemetry?.fields {
                            ForEach(Array(fields.keys), id: \.self) { key in
                                if let field = fields[key], let polyArray = field.polygon {
                                    let coords = polyArray.map { CLLocationCoordinate2D(latitude: $0[0], longitude: $0[1]) }
                                    let isMine = (field.owner == network.clientId)
                                    MapPolygon(coordinates: coords)
                                        .foregroundStyle(isMine ? .green.opacity(0.4) : .red.opacity(0.4))
                                        .stroke(isMine ? .green : .red, lineWidth: 3)
                                    
                                    Annotation(key, coordinate: CLLocationCoordinate2D(latitude: field.lat, longitude: field.lon)) {
                                        VStack {
                                            Text(key).font(.caption2).bold()
                                            Text(field.owner ?? "").font(.system(size: 8))
                                        }.padding(4).background(Color.black.opacity(0.7)).foregroundColor(.white).cornerRadius(4)
                                    }
                                }
                            }
                        }
                        
                        // 2. UÇAN DRONLAR
                        if let drones = network.telemetry?.drones {
                            ForEach(Array(drones.keys), id: \.self) { droneId in
                                let d = drones[droneId]!
                                let isMyDrone = (droneId == network.clientId)
                                Annotation(droneId, coordinate: CLLocationCoordinate2D(latitude: d.lat, longitude: d.lon)) {
                                    VStack(spacing: 0) {
                                        Text("🚁").font(.system(size: isMyDrone ? 35 : 25))
                                            .shadow(color: isMyDrone ? .cyan : .orange, radius: isMyDrone ? 8 : 3)
                                        Text(droneId).font(.system(size: 9)).bold()
                                            .padding(2).background(Color.black.opacity(0.6)).foregroundColor(isMyDrone ? .cyan : .orange).cornerRadius(4)
                                    }
                                }
                            }
                        }
                        
                        // 3. ÇİZİM GÖRSELLERİ
                        if network.drawMode == .field && !network.tempCoords.isEmpty {
                            let drawnCoords = network.tempCoords + [network.tempCoords.first!]
                            MapPolyline(coordinates: drawnCoords).stroke(.yellow, lineWidth: 3)
                            ForEach(Array(network.tempCoords.enumerated()), id: \.offset) { _, coord in
                                Annotation("", coordinate: coord) { Circle().fill(Color.yellow).frame(width: 10, height: 10) }
                            }
                        }
                        if network.drawMode == .droneBase, let base = network.tempBase {
                            Annotation("Yeni Üs", coordinate: base) {
                                Image(systemName: "house.fill").font(.title).foregroundColor(.orange)
                            }
                        }
                    }
                    .mapStyle(.imagery)
                    .onTapGesture { position in
                        if let coord = proxy.convert(position, from: .local) {
                            if network.drawMode == .field { network.tempCoords.append(coord) }
                            else if network.drawMode == .droneBase { network.tempBase = coord }
                        }
                    }
                }
            }
        }
        // UYARI VE PENCERELER
        .alert(isPresented: $network.showAlert) {
            Alert(title: Text("Kule Mesajı"), message: Text(network.alertMessage), dismissButton: .default(Text("Tamam")))
        }
        .alert("Yeni Dron ve Üs Adı", isPresented: $showingDroneDialog) {
            TextField("Örn: HASAN_DRON", text: $newNameInput)
            Button("İptal", role: .cancel) { newNameInput = "" }
            Button("Kuleye Gönder") {
                if !newNameInput.isEmpty { network.requestNewDrone(name: newNameInput); newNameInput = "" }
            }
        }
        .alert("Yeni Tarla Adı", isPresented: $showingFieldDialog) {
            TextField("Örn: Yonca Tarlası", text: $newNameInput)
            Button("İptal", role: .cancel) { newNameInput = "" }
            Button("Kuleye Gönder") {
                if !newNameInput.isEmpty { network.requestNewField(name: newNameInput); newNameInput = "" }
            }
        }
        .alert("Test İçin Kimlik Değiştir", isPresented: $showingIdentityAlert) {
            TextField("Dron/Kullanıcı Adı", text: $newNameInput)
            Button("İptal", role: .cancel) { newNameInput = "" }
            Button("Değiştir") {
                if !newNameInput.isEmpty { network.clientId = newNameInput; newNameInput = "" }
            }
        } message: { Text("Başka bir çiftçinin sistemine geçmiş gibi test yapmak için dron adını değiştirin.") }
    }
}

// --- 5. TARLALARIM (SADECE BENİM TARLALARIM) ---
struct FieldsTabView: View {
    @ObservedObject var network: TelemetryManager
    @State private var showingResprayAlert = false
    @State private var fieldToRespray: String? = nil
    
    var body: some View {
        NavigationView {
            ZStack {
                Color.black.edgesIgnoringSafeArea(.all)
                if let fields = network.telemetry?.fields {
                    let myFields = fields.filter { $0.value.owner == network.clientId }.sorted { $0.key < $1.key }
                    
                    if myFields.isEmpty {
                        VStack(spacing: 20) {
                            Image(systemName: "xmark.bin.fill").font(.largeTitle).foregroundColor(.red)
                            Text("Sisteme kayıtlı veya size (\(network.clientId)) ait\nonaylanmış bir tarla bulunmuyor.").foregroundColor(.gray).multilineTextAlignment(.center)
                        }
                    } else {
                        List(myFields, id: \.key) { key, field in
                            VStack(alignment: .leading, spacing: 8) {
                                HStack {
                                    Text("🌾 \(key)").font(.headline).foregroundColor(.white)
                                    Spacer()
                                    Text(String(format: "%.2f Dönüm", field.acre)).font(.subheadline).foregroundColor(.green)
                                }
                                let progress = min(1.0, field.sprayed_acre / field.acre)
                                ProgressView(value: progress).accentColor(progress >= 1.0 ? .blue : .green)
                                
                                HStack {
                                    Text("İlaçlanan: \(String(format: "%.2f", field.sprayed_acre))").font(.caption).foregroundColor(.gray)
                                    Spacer()
                                    Button(action: {
                                        if field.sprayed_acre >= field.acre {
                                            fieldToRespray = key
                                            showingResprayAlert = true
                                        } else { network.startMission(fieldName: key) }
                                    }) {
                                        Text("🚀 GÖREVE YOLLA").font(.caption).bold()
                                            .padding(.horizontal, 12).padding(.vertical, 6)
                                            .background(Color.green).foregroundColor(.black).cornerRadius(6)
                                    }
                                }
                            }
                            .padding(.vertical, 5).listRowBackground(Color(white: 0.15))
                        }.scrollContentBackground(.hidden)
                    }
                } else { ProgressView("Kuleye Bağlanılıyor...") }
            }
            .navigationTitle("Tarlalarım")
            .navigationBarTitleDisplayMode(.inline)
            .alert("Zaten İlaçlanmış Tarla", isPresented: $showingResprayAlert) {
                Button("İptal", role: .cancel) { fieldToRespray = nil }
                Button("Yine de Başlat") {
                    if let fName = fieldToRespray { network.startMission(fieldName: fName); fieldToRespray = nil }
                }
            } message: { Text("Bu tarla tamamen ilaçlanmış görünüyor. Tekrar göndermek istediğinize emin misiniz?") }
        }
    }
}

// --- 6. OPERASYON (SADECE BENİM DRONUM) ---
struct OperationsTabView: View {
    @ObservedObject var network: TelemetryManager
    
    var body: some View {
        ZStack {
            Color.black.edgesIgnoringSafeArea(.all)
            VStack(spacing: 20) {
                Text("OPERASYON MERKEZİ: \(network.clientId)")
                    .font(.title3).bold().foregroundColor(.white).padding(.top, 20)
                
                if let myDrone = network.telemetry?.drones?[network.clientId] {
                    VStack(alignment: .leading, spacing: 15) {
                        HStack {
                            Text("🚁 Sistem Durumu:").font(.subheadline).foregroundColor(.gray)
                            Spacer()
                            Text(myDrone.state).font(.subheadline).bold().foregroundColor(.cyan)
                                .padding(.horizontal, 8).padding(.vertical, 4).background(Color.cyan.opacity(0.2)).cornerRadius(6)
                        }
                        HStack {
                            StatBox(icon: "battery.100", title: "BATARYA", value: String(format: "%.1f %%", myDrone.battery), color: myDrone.battery > 20 ? .green : .red)
                            StatBox(icon: "drop.fill", title: "İLAÇ", value: String(format: "%.1f L", myDrone.chemical), color: .cyan)
                            StatBox(icon: "speedometer", title: "HIZ", value: "\(myDrone.speed_kmh) km/h", color: .yellow)
                        }
                    }.padding().background(Color(white: 0.15)).cornerRadius(12).padding(.horizontal)
                    Spacer()
                } else {
                    Spacer()
                    VStack {
                        Image(systemName: "antenna.radiowaves.left.and.right.slash").font(.largeTitle).foregroundColor(.red).padding()
                        Text("[\(network.clientId)] dronu Kulede kayıtlı değil!\nLütfen Radar sekmesinden 'ÜS KUR' diyerek dronunuzu kaydedin ve Kule'den onaylayın.")
                            .foregroundColor(.gray).multilineTextAlignment(.center).padding()
                    }
                    Spacer()
                }
            }
        }
    }
}

struct StatBox: View {
    var icon: String; var title: String; var value: String; var color: Color
    var body: some View {
        VStack(spacing: 8) {
            Image(systemName: icon).font(.title2).foregroundColor(color)
            Text(title).font(.caption2).foregroundColor(.gray)
            Text(value).font(.subheadline).fontWeight(.bold).foregroundColor(.white)
        }
        .frame(maxWidth: .infinity).padding(.vertical, 12).background(Color.black.opacity(0.4)).cornerRadius(8)
    }
}
